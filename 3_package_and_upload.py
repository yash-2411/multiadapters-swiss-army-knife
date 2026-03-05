import os
import shutil
import tempfile
import tarfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = None
AWS_REGION = None
SAGEMAKER_ROLE_ARN = None


def validate_prerequisites() -> None:
    required = [
        Path("./adapters/adapter_1/adapter_config.json"),
        Path("./adapters/adapter_2/adapter_config.json"),
        Path("./adapters/adapter_3/adapter_config.json"),
        Path("./sagemaker_artifacts/serving.properties"),
        Path("./sagemaker_artifacts/model.py"),
        Path("./sagemaker_artifacts/model_handler.py"),
    ]
    for p in required:
        if not p.exists():
            print(f"[X] Missing required file: {p.absolute()}")
            print("   Run: python 2_create_adapters.py first")
            exit(1)


def load_config() -> None:
    global S3_BUCKET, AWS_REGION, SAGEMAKER_ROLE_ARN
    S3_BUCKET = os.getenv("S3_BUCKET")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    SAGEMAKER_ROLE_ARN = os.getenv("SAGEMAKER_ROLE_ARN")
    if not S3_BUCKET:
        print("[X] S3_BUCKET not set in .env")
        exit(1)


def create_package(package_dir: Path) -> None:
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "adapters").mkdir(exist_ok=True)

    shutil.copy(Path("./sagemaker_artifacts/serving.properties"), package_dir / "serving.properties")
    shutil.copy(Path("./sagemaker_artifacts/model.py"), package_dir / "model.py")
    shutil.copy(Path("./sagemaker_artifacts/model_handler.py"), package_dir / "model_handler.py")

    for adapter in ["adapter_1", "adapter_2", "adapter_3"]:
        src = Path(f"./adapters/{adapter}")
        dst = package_dir / "adapters" / adapter
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def create_tar_gz(package_dir: Path, output_path: Path) -> float:
    print("Packaging: serving.properties, model.py, model_handler.py, 3 adapters...")
    with tarfile.open(output_path, "w:gz") as tar:
        for item in package_dir.rglob("*"):
            if item.is_file():
                arcname = item.relative_to(package_dir)
                tar.add(item, arcname=arcname)
    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Package size: {size_mb:.1f} MB")
    return size_mb


def upload_to_s3(local_path: Path) -> str:
    s3_key = "multi-lora-model/model.tar.gz"
    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        file_size = local_path.stat().st_size
        if file_size <= 0:
            raise ValueError("Package file is empty. Packaging may have failed.")

        class ProgressTracker:
            def __init__(self):
                self.uploaded = 0
                self.last_pct = 0

            def __call__(self, bytes_transferred):
                self.uploaded += bytes_transferred
                pct = int(100 * self.uploaded / file_size)
                if pct >= self.last_pct + 10 and pct <= 100:
                    print(f"  Upload progress: {pct}%")
                    self.last_pct = pct

        config = boto3.s3.transfer.TransferConfig(
            multipart_threshold=8 * 1024 * 1024,
            max_concurrency=4,
        )
        s3.upload_file(
            str(local_path),
            S3_BUCKET,
            s3_key,
            Config=config,
            Callback=ProgressTracker(),
        )
        print(f"[OK] Uploaded to {s3_uri}")
        return s3_uri
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchBucket":
            print(f"[X] S3 bucket '{S3_BUCKET}' does not exist.")
            print("   Create it: aws s3 mb s3://your-bucket-name")
            exit(1)
        elif error_code == "AccessDenied":
            print("[X] Access denied to S3.")
            print("   Ensure your IAM role has s3:PutObject permission on the bucket.")
            exit(1)
        raise
    except FileNotFoundError:
        print("[X] Package file not found. Run packaging step first.")
        exit(1)


def main():
    validate_prerequisites()
    load_config()
    with tempfile.TemporaryDirectory() as tmpdir:
        package_dir = Path(tmpdir) / "package"
        create_package(package_dir)
        output_path = Path("model.tar.gz")
        create_tar_gz(package_dir, output_path)
    s3_uri = upload_to_s3(output_path)
    Path(".s3_uri").write_text(s3_uri)
    print(f"   S3 URI: {s3_uri}")
    print("   Next: python 4_deploy_endpoint.py")


if __name__ == "__main__":
    main()
