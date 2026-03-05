import json
import os
import secrets
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
ACCOUNT_ID = boto3.client("sts", region_name=AWS_REGION).get_caller_identity()["Account"]

LAMBDA_ROLE_NAME = "MultiLoRASwissKnifeRole"
BACKEND_FUNCTION_NAME = "multi-lora-swissknife-router"
DASHBOARD_FUNCTION_NAME = "multi-lora-swissknife-dashboard"
API_NAME = "multi-lora-swissknife-api"
USAGE_PLAN_NAME = "multi-lora-swissknife-usage-plan"
API_KEY_NAME = "multi-lora-swissknife-api-key"


def create_lambda_role(iam_client) -> str:

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }

    try:
        role = iam_client.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Role for Multi-LoRA Swiss Knife Lambda functions",
        )
        role_arn = role["Role"]["Arn"]
    except iam_client.exceptions.EntityAlreadyExistsException:
        role_arn = iam_client.get_role(RoleName=LAMBDA_ROLE_NAME)["Role"]["Arn"]

    for policy in [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess",
    ]:
        try:
            iam_client.attach_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyArn=policy)
        except Exception:
            pass

    time.sleep(12)
    return role_arn


def zip_backend() -> str:

    zip_path = Path(tempfile.gettempdir()) / "backend_package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("lambda/handler.py", "handler.py")
        for f in Path("utils").glob("*.py"):
            zf.write(f, f"utils/{f.name}")

    return str(zip_path)


def zip_dashboard() -> str:

    zip_path = Path(tempfile.gettempdir()) / "dashboard_package.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("lambda/dashboard_handler.py", "handler.py")

    return str(zip_path)


def deploy_function(lambda_client, function_name: str, zip_path: str,
                    role_arn: str, env_vars: dict, timeout: int = 120) -> str:
    zip_bytes = Path(zip_path).read_bytes()

    try:
        response = lambda_client.create_function(
            FunctionName=function_name,
            Runtime="python3.11",
            Role=role_arn,
            Handler="handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=timeout,
            MemorySize=256,
            Environment={"Variables": env_vars},
        )
        arn = response["FunctionArn"]
    except lambda_client.exceptions.ResourceConflictException:
        lambda_client.update_function_code(FunctionName=function_name, ZipFile=zip_bytes)
        time.sleep(5)
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Timeout=timeout,
            MemorySize=256,
            Environment={"Variables": env_vars},
        )
        arn = lambda_client.get_function(FunctionName=function_name)["Configuration"]["FunctionArn"]

    waiter = lambda_client.get_waiter("function_active_v2")
    waiter.wait(FunctionName=function_name)
    return arn


def build_api_gateway(apigw_client, lambda_client, backend_arn: str, dashboard_arn: str):

    apis = apigw_client.get_rest_apis()["items"]
    existing = next((a for a in apis if a["name"] == API_NAME), None)

    if existing:
        api_id = existing["id"]
    else:
        api = apigw_client.create_rest_api(
            name=API_NAME,
            description="Multi-LoRA Swiss Knife - router + dashboard",
            endpointConfiguration={"types": ["REGIONAL"]},
        )
        api_id = api["id"]

    resources = apigw_client.get_resources(restApiId=api_id)["items"]
    root_id = next(r["id"] for r in resources if r["path"] == "/")

    def _lambda_uri(arn):
        return f"arn:aws:apigateway:{AWS_REGION}:lambda:path/2015-03-31/functions/{arn}/invocations"

    def _grant_permission(fn_name, stmt_id):
        try:
            lambda_client.add_permission(
                FunctionName=fn_name,
                StatementId=stmt_id,
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                SourceArn=f"arn:aws:execute-api:{AWS_REGION}:{ACCOUNT_ID}:{api_id}/*/*",
            )
        except lambda_client.exceptions.ResourceConflictException:
            pass

    def _create_resource(path_part, parent_id):
        existing_res = next((r for r in resources if r.get("pathPart") == path_part), None)
        if existing_res:
            return existing_res["id"]
        res = apigw_client.create_resource(
            restApiId=api_id, parentId=parent_id, pathPart=path_part
        )
        return res["id"]

    def _attach_lambda_proxy(resource_id, uri, require_api_key: bool):
        try:
            apigw_client.put_method(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod="ANY",
                authorizationType="NONE",
                apiKeyRequired=require_api_key,
            )
        except apigw_client.exceptions.ConflictException:
            pass
        try:
            apigw_client.put_integration(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod="ANY",
                type="AWS_PROXY",
                integrationHttpMethod="POST",
                uri=uri,
            )
        except apigw_client.exceptions.ConflictException:
            pass

    dashboard_res_id = _create_resource("dashboard", root_id)
    _attach_lambda_proxy(dashboard_res_id, _lambda_uri(dashboard_arn), require_api_key=False)
    _grant_permission(DASHBOARD_FUNCTION_NAME, "APIGWDashboard")

    generate_res_id = _create_resource("generate", root_id)
    _attach_lambda_proxy(generate_res_id, _lambda_uri(backend_arn), require_api_key=True)

    health_res_id = _create_resource("health", root_id)
    _attach_lambda_proxy(health_res_id, _lambda_uri(backend_arn), require_api_key=True)

    metrics_res_id = _create_resource("metrics", root_id)
    _attach_lambda_proxy(metrics_res_id, _lambda_uri(backend_arn), require_api_key=True)

    _grant_permission(BACKEND_FUNCTION_NAME, "APIGWBackend")

    apigw_client.create_deployment(
        restApiId=api_id,
        stageName="prod",
        description="Multi-LoRA Swiss Knife prod",
    )

    api_url = f"https://{api_id}.execute-api.{AWS_REGION}.amazonaws.com/prod"
    return api_id, api_url


def create_api_key(apigw_client, api_id: str):

    existing_keys = apigw_client.get_api_keys(includeValues=True)["items"]
    existing = next((k for k in existing_keys if k["name"] == API_KEY_NAME), None)

    if existing:
        key_id = existing["id"]
        key_value = existing["value"]
    else:
        key = apigw_client.create_api_key(
            name=API_KEY_NAME,
            description="Multi-LoRA Swiss Knife API key for backend routes",
            enabled=True,
        )
        key_id = key["id"]
        key_value = key["value"]

    existing_plans = apigw_client.get_usage_plans()["items"]
    plan = next((p for p in existing_plans if p["name"] == USAGE_PLAN_NAME), None)

    if not plan:
        plan = apigw_client.create_usage_plan(
            name=USAGE_PLAN_NAME,
            description="Multi-LoRA Swiss Knife usage plan",
            apiStages=[{"apiId": api_id, "stage": "prod"}],
            throttle={"rateLimit": 10, "burstLimit": 20},
            quota={"limit": 1000, "period": "DAY"},
        )
        plan_id = plan["id"]
    else:
        plan_id = plan["id"]

    try:
        apigw_client.create_usage_plan_key(
            usagePlanId=plan_id,
            keyId=key_id,
            keyType="API_KEY",
        )
    except apigw_client.exceptions.ConflictException:
        pass

    return key_id, key_value


def update_dashboard_env(lambda_client, api_url: str, api_key_value: str, dashboard_token: str):

    lambda_client.update_function_configuration(
        FunctionName=DASHBOARD_FUNCTION_NAME,
        Environment={
            "Variables": {
                "API_URL": api_url,
                "DASHBOARD_API_KEY": api_key_value,
                "DASHBOARD_TOKEN": dashboard_token,
            }
        },
    )
    time.sleep(5)


def main():
    for p in [Path("lambda/handler.py"), Path("lambda/dashboard_handler.py"),
              Path("utils/config.py"), Path("utils/metrics.py")]:
        if not p.exists():
            print(f"[X] Missing {p}. Run from project root.")
            sys.exit(1)

    iam = boto3.client("iam", region_name=AWS_REGION)
    lc = boto3.client("lambda", region_name=AWS_REGION)
    agw = boto3.client("apigateway", region_name=AWS_REGION)

    endpoint_name = os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")

    role_arn = create_lambda_role(iam)

    backend_zip = zip_backend()
    dashboard_zip = zip_dashboard()


    backend_arn = deploy_function(lc, BACKEND_FUNCTION_NAME, backend_zip, role_arn, {
        "APP_REGION": AWS_REGION,
        "ENDPOINT_NAME": endpoint_name,
    }, timeout=120)

    dashboard_arn = deploy_function(lc, DASHBOARD_FUNCTION_NAME, dashboard_zip, role_arn, {
        "API_URL": "PLACEHOLDER",
        "DASHBOARD_API_KEY": "PLACEHOLDER",
        "DASHBOARD_TOKEN": "PLACEHOLDER",
    }, timeout=10)

    api_id, api_url = build_api_gateway(agw, lc, backend_arn, dashboard_arn)

    key_id, key_value = create_api_key(agw, api_id)

    dashboard_token = secrets.token_urlsafe(32)

    update_dashboard_env(lc, api_url, key_value, dashboard_token)


    dashboard_url = f"{api_url}/dashboard?token={dashboard_token}"

    config = {
        "api_url": api_url,
        "api_key": key_value,
        "dashboard_token": dashboard_token,
        "dashboard_url": dashboard_url,
        "backend_lambda": BACKEND_FUNCTION_NAME,
        "dashboard_lambda": DASHBOARD_FUNCTION_NAME,
        "endpoints": {
            "dashboard": f"{dashboard_url}  (token-protected)",
            "generate": f"{api_url}/generate  (POST, x-api-key required)",
            "health": f"{api_url}/health    (GET,  x-api-key required)",
            "metrics": f"{api_url}/metrics   (GET,  x-api-key required)",
        },
    }
    Path("lambda_deployment.json").write_text(json.dumps(config, indent=2))

    print(f"Dashboard: {dashboard_url}")
    print(f"API key: {key_value}")
    print("Config: lambda_deployment.json")


if __name__ == "__main__":
    main()
