import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(
    page_title="Multi-LoRA Swiss Army Knife",
    page_icon="🔧",
    layout="wide",
)

_api_config = Path("lambda_deployment.json")
if _api_config.exists():
    try:
        API_BASE = json.loads(_api_config.read_text())["api_url"]
    except (json.JSONDecodeError, KeyError):
        API_BASE = "http://localhost:8000"
else:
    API_BASE = "http://localhost:8000"

st.title("🔧 Multi-LoRA Swiss Army Knife")
st.caption("Llama 3.1 8B AWQ. Three LoRA adapters. One GPU. ~67% cost savings.")

with st.sidebar:
    st.header("⚙️ Configuration")
    domain = st.selectbox(
        "Adapter",
        ["auto", "adapter_1", "adapter_2", "adapter_3", "none"],
        format_func=lambda x: {"auto": "Auto-detect", "adapter_1": "Legal", "adapter_2": "Medical", "adapter_3": "Coding", "none": "Base Model"}.get(x, x),
        help="'auto' detects adapter from your prompt keywords",
    )
    max_tokens = st.slider("Max Tokens", 64, 1024, 512, 64)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)

    st.divider()
    st.header("💰 Cost Tracker")

    try:
        metrics_resp = requests.get(f"{API_BASE}/metrics", timeout=2)
        if metrics_resp.status_code == 200:
            metrics = metrics_resp.json()
            st.metric("Total Requests", metrics.get("total_requests", 0))
            st.metric("Total Cost", f"${metrics.get('total_cost_usd', 0):.4f}")
            st.metric("Avg Latency", f"{metrics.get('avg_latency_ms', 0):.0f}ms")
    except Exception:
        st.caption("Start endpoint: python 4_deploy_endpoint.py (takes 15 min)")

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("💬 Generate")
    prompt = st.text_area(
        "Enter your prompt:",
        height=120,
        placeholder="Try: 'What is indemnification?' or 'Write a binary search function' or 'Explain ACE inhibitors'",
    )

    generate_btn = st.button("⚡ Generate", type="primary", use_container_width=True)

    if generate_btn and prompt:
        with st.spinner("Routing to adapter and generating..."):
            try:
                start = time.time()
                resp = requests.post(
                    f"{API_BASE}/generate",
                    json={"prompt": prompt, "domain": domain, "max_tokens": max_tokens, "temperature": temperature},
                    timeout=120,
                )
                elapsed = (time.time() - start) * 1000

                if resp.status_code == 200:
                    data = resp.json()

                    st.success("✅ Response generated")
                    st.text_area("Response:", value=data["response"], height=200, disabled=True)

                    m1, m2, m3, m4 = st.columns(4)
                    adapter_display = {"adapter_1": "Legal", "adapter_2": "Medical", "adapter_3": "Coding", "base_model": "Base Model"}.get(data["adapter_used"], data["adapter_used"])
                    m1.metric("Adapter Used", adapter_display)
                    m2.metric("Latency", f"{data['latency_ms']:.0f}ms")
                    m3.metric("Tokens", data["tokens_generated"])
                    m4.metric("Cost", f"${data['estimated_cost_usd']:.6f}")

                    if domain == "auto":
                        domain_display = {"adapter_1": "Legal", "adapter_2": "Medical", "adapter_3": "Coding"}.get(data["domain_detected"], data.get("domain_detected", ""))
                        st.info(f"🎯 Auto-detected: **{domain_display}** based on prompt keywords")

                    if "history" not in st.session_state:
                        st.session_state.history = []
                    st.session_state.history.insert(
                        0,
                        {
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "adapter": data["adapter_used"],
                            "latency_ms": data["latency_ms"],
                            "tokens": data["tokens_generated"],
                            "cost": data["estimated_cost_usd"],
                            "prompt_preview": prompt[:60] + "..." if len(prompt) > 60 else prompt,
                        },
                    )
                    st.session_state.history = st.session_state.history[:10]
                else:
                    error_detail = resp.json().get("detail", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                    if "not running" in str(error_detail).lower() or resp.status_code == 503:
                        st.error("Endpoint not running. Run: python 4_deploy_endpoint.py")
                    else:
                        st.error(f"Error {resp.status_code}: {error_detail}")

            except requests.exceptions.ConnectionError:
                st.error("Cannot connect to API. Deploy Lambda: python 1_deploy_lambda.py")
            except Exception as e:
                st.error(f"Error: {str(e)}")

with col2:
    st.subheader("📊 VRAM Comparison")

    fig = go.Figure(
        go.Bar(
            x=["3 FP16 Models\n(Traditional)", "3 INT8 Models\n(Traditional)", "Multi-LoRA INT8\n(This Project)"],
            y=[48.0, 24.0, 8.5],
            marker_color=["#ef4444", "#f97316", "#22c55e"],
            text=["48.0 GB\n$4.56/hr", "24.0 GB\n$2.82/hr", "8.5 GB\n$0.94/hr"],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="GPU VRAM Required",
        yaxis_title="VRAM (GB)",
        showlegend=False,
        height=300,
        margin=dict(t=40, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("🧩 Adapter Registry")
    adapter_data = {
        "Adapter": ["Legal", "Medical", "Coding"],
        "Size": ["~80 MB", "~80 MB", "~80 MB"],
        "Status": ["✅ Loaded", "✅ Loaded", "✅ Loaded"],
    }
    st.dataframe(pd.DataFrame(adapter_data), hide_index=True, use_container_width=True)

st.divider()
st.subheader("💡 Why This Matters")

c1, c2, c3 = st.columns(3)
with c1:
    st.error("**Traditional: 3 Instances**\n\n3 × $0.94/hr = **$2.82/hr**\n\n3 × 8GB = **24GB VRAM**\n\n3 model deployments to manage")
with c2:
    st.success("**Multi-LoRA: 1 Instance**\n\n1 × $0.94/hr = **$0.94/hr**\n\n8.5GB = **8.5GB VRAM**\n\n1 deployment, 3 adapters")
with c3:
    st.info("**Savings**\n\n**66% cost reduction**\n\n**65% less VRAM**\n\nScales to 50+ adapters")

if "history" in st.session_state and st.session_state.history:
    st.divider()
    st.subheader("📋 Request History (Last 10)")
    st.dataframe(
        pd.DataFrame(st.session_state.history),
        hide_index=True,
        use_container_width=True,
    )
