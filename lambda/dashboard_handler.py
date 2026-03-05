import os
import json


def lambda_handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")

    if method == "GET" and path in ("/", "/dashboard"):
        expected_token = os.environ.get("DASHBOARD_TOKEN", "")
        query_params = event.get("queryStringParameters") or {}
        provided_token = query_params.get("token", "")

        if not expected_token or provided_token != expected_token:
            return {
                "statusCode": 403,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({
                    "error": "Forbidden",
                    "message": "Valid ?token= parameter required to access the dashboard.",
                }),
            }

        api_url = os.environ.get("API_URL", "")
        api_key = os.environ.get("DASHBOARD_API_KEY", "")
        html = build_dashboard_html(api_url, api_key)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/html",
                "Cache-Control": "no-cache, no-store",
            },
            "body": html,
        }

    return {
        "statusCode": 404,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": "Not found"}),
    }


def build_dashboard_html(api_url: str, api_key: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Multi-LoRA Swiss Army Knife</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f1117; color: #e0e0e0; min-height: 100vh; padding: 20px;
  }}

  .header {{ text-align: center; padding: 32px 0 24px; border-bottom: 1px solid #2a2d3a; margin-bottom: 32px; }}
  .header h1 {{ font-size: 2rem; font-weight: 700; color: #fff; letter-spacing: -0.5px; }}
  .header h1 span {{ color: #4f9cf9; }}
  .header p {{ color: #8b8fa8; margin-top: 8px; font-size: 0.95rem; }}

  .grid {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 24px;
    max-width: 1200px; margin: 0 auto;
  }}
  @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}

  .card {{
    background: #1a1d2e; border: 1px solid #2a2d3a;
    border-radius: 12px; padding: 24px;
  }}
  .card h2 {{
    font-size: 1rem; font-weight: 600; color: #8b8fa8;
    text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 16px;
  }}
  .full-width {{ grid-column: 1 / -1; }}

  .status-bar {{
    display: flex; gap: 20px; max-width: 1200px; margin: 0 auto 24px;
    background: #1a1d2e; border: 1px solid #2a2d3a; border-radius: 12px;
    padding: 16px 24px; align-items: center; flex-wrap: wrap;
  }}
  .status-item {{ display: flex; align-items: center; gap: 8px; font-size: 0.9rem; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; }}
  .dot.green {{ background: #22c55e; box-shadow: 0 0 8px #22c55e; }}
  .dot.red {{ background: #ef4444; box-shadow: 0 0 8px #ef4444; }}
  .dot.yellow {{ background: #eab308; box-shadow: 0 0 8px #eab308; }}
  .status-label {{ color: #8b8fa8; }}
  .status-val {{ color: #fff; font-weight: 600; }}

  textarea, select, input[type=range] {{
    width: 100%; background: #0f1117; border: 1px solid #2a2d3a;
    border-radius: 8px; color: #e0e0e0; font-size: 0.95rem;
    padding: 12px; resize: vertical; outline: none; transition: border-color 0.2s;
  }}
  textarea:focus, select:focus {{ border-color: #4f9cf9; }}
  select {{ padding: 10px 12px; cursor: pointer; }}
  .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px; }}
  label {{
    display: block; font-size: 0.8rem; color: #8b8fa8;
    text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 6px;
  }}

  button {{ cursor: pointer; border: none; border-radius: 8px; font-weight: 600; transition: all 0.2s; }}
  .btn-primary {{
    background: #4f9cf9; color: #fff; padding: 12px 28px;
    font-size: 1rem; width: 100%; margin-top: 16px;
  }}
  .btn-primary:hover {{ background: #3b82f6; transform: translateY(-1px); }}
  .btn-primary:disabled {{ background: #2a2d3a; color: #4a4d5a; cursor: not-allowed; transform: none; }}

  .response-box {{
    background: #0f1117; border: 1px solid #2a2d3a; border-radius: 8px;
    padding: 16px; min-height: 120px; font-size: 0.95rem; line-height: 1.6;
    color: #e0e0e0; white-space: pre-wrap; word-wrap: break-word;
  }}
  .response-box.empty {{ color: #4a4d5a; font-style: italic; }}
  .response-box.loading {{ color: #4f9cf9; }}
  .response-box.error {{ color: #ef4444; border-color: #ef4444; }}

  .metrics-row {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 10px; margin-top: 16px;
  }}
  @media (max-width: 900px) {{ .metrics-row {{ grid-template-columns: repeat(2, 1fr); }} }}
  .metric-box {{
    background: #0f1117; border: 1px solid #2a2d3a;
    border-radius: 8px; padding: 10px; text-align: center;
  }}
  .metric-label {{
    font-size: 0.68rem; color: #8b8fa8; text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .metric-val {{ font-size: 1rem; font-weight: 700; color: #4f9cf9; margin-top: 3px; }}
  .metric-val.green {{ color: #22c55e; }}
  .metric-val.orange {{ color: #f97316; }}
  .metric-val.cyan {{ color: #06b6d4; }}
  .metric-val.purple {{ color: #a78bfa; }}

  .badge {{
    display: inline-block; background: #1e3a5f; color: #4f9cf9;
    border: 1px solid #2563eb; border-radius: 20px; padding: 4px 12px;
    font-size: 0.8rem; font-weight: 600; margin-top: 8px;
  }}

  .cost-bars {{ margin-bottom: 18px; }}
  .cost-bar-row {{ margin-bottom: 12px; }}
  .cost-bar-header {{
    display: flex; justify-content: space-between; align-items: center;
    font-size: 0.82rem; margin-bottom: 4px;
  }}
  .cost-bar-header span:first-child {{ color: #8b8fa8; }}
  .cost-bar-header span:last-child {{ color: #fff; font-weight: 600; }}
  .cost-bar-bg {{
    background: #0f1117; border-radius: 4px; height: 14px; overflow: hidden;
  }}
  .cost-bar-fill {{
    height: 100%; border-radius: 4px; transition: width 0.8s ease;
  }}
  .bar-green {{ background: linear-gradient(90deg, #22c55e, #16a34a); }}
  .bar-orange {{ background: linear-gradient(90deg, #f97316, #ea580c); }}
  .bar-red {{ background: linear-gradient(90deg, #ef4444, #dc2626); }}
  .cost-bar-tag {{
    display: inline-block; font-size: 0.7rem; font-weight: 600;
    padding: 1px 8px; border-radius: 10px; margin-left: 8px;
  }}
  .cost-bar-tag.you {{ background: #1a3a2f; color: #22c55e; }}

  .cost-subtitle {{
    font-size: 0.78rem; color: #4a4d5a; margin-bottom: 16px; line-height: 1.4;
  }}
  .cost-section-label {{
    font-size: 0.72rem; color: #6b7280; text-transform: uppercase;
    letter-spacing: 0.6px; margin-bottom: 8px; margin-top: 16px;
  }}
  .cost-section-label:first-of-type {{ margin-top: 0; }}
  .cost-row {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 6px 0; border-bottom: 1px solid #1e2030;
  }}
  .cost-row:last-child {{ border-bottom: none; }}
  .cost-row-label {{ font-size: 0.85rem; color: #8b8fa8; }}
  .cost-row-value {{ font-size: 0.9rem; font-weight: 600; color: #fff; }}
  .cost-row-value.green {{ color: #22c55e; }}
  .cost-row-value.red {{ color: #ef4444; }}
  .cost-row-value.blue {{ color: #4f9cf9; }}
  .cost-row-value.big {{ font-size: 1.1rem; }}
  .cost-offline {{
    text-align: center; padding: 20px 0; color: #4a4d5a; font-style: italic;
  }}

  .adapter-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  .adapter-table th {{
    text-align: left; font-size: 0.75rem; color: #8b8fa8;
    text-transform: uppercase; letter-spacing: 0.6px; padding: 8px;
    border-bottom: 1px solid #2a2d3a;
  }}
  .adapter-table td {{ padding: 10px 8px; font-size: 0.9rem; border-bottom: 1px solid #1a1d2e; }}
  .tag {{
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 0.8rem; font-weight: 600;
  }}
  .tag-adapter1 {{ background: #1e3a5f; color: #60a5fa; }}
  .tag-adapter2 {{ background: #1a3a2f; color: #34d399; }}
  .tag-adapter3 {{ background: #3a1f5f; color: #c084fc; }}
  .tag-base {{ background: #2a2d3a; color: #8b8fa8; }}
  .tag-online {{ background: #1a3a2f; color: #22c55e; }}

  .history-wrap {{ overflow-x: auto; }}
  .history-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.85rem; }}
  .history-table th {{
    text-align: left; color: #8b8fa8; font-size: 0.7rem;
    text-transform: uppercase; letter-spacing: 0.5px; padding: 6px 8px;
    border-bottom: 1px solid #2a2d3a; white-space: nowrap;
  }}
  .history-table td {{
    padding: 8px; border-bottom: 1px solid #1a1d2e; color: #c0c0c8; white-space: nowrap;
  }}
  .empty-history {{ color: #4a4d5a; font-style: italic; text-align: center; padding: 24px; }}

  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .spinner {{
    display: inline-block; width: 16px; height: 16px;
    border: 2px solid #2a2d3a; border-top-color: #4f9cf9;
    border-radius: 50%; animation: spin 0.8s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Multi-LoRA Swiss Army Knife</h1>
  <p>Llama 3.1 8B AWQ &middot; Three LoRA adapters &middot; Text-only &middot; ml.g5.xlarge (A10G 24GB)</p>
</div>

<div class="status-bar">
  <div class="status-item">
    <div class="dot yellow" id="endpointDot"></div>
    <span class="status-label">Endpoint:</span>
    <span class="status-val" id="endpointStatus">Checking...</span>
  </div>
  <div class="status-item">
    <div class="dot green"></div>
    <span class="status-label">Lambda:</span>
    <span class="status-val">Online</span>
  </div>
  <div class="status-item">
    <span class="status-label">Requests:</span>
    <span class="status-val" id="totalReqs">&mdash;</span>
  </div>
  <div class="status-item">
    <span class="status-label">Avg TTFT:</span>
    <span class="status-val" id="avgTTFT">&mdash;</span>
  </div>
  <div class="status-item">
    <span class="status-label">Avg Throughput:</span>
    <span class="status-val" id="avgTPS">&mdash;</span>
  </div>
  <div class="status-item">
    <span class="status-label">Infra Cost (Session):</span>
    <span class="status-val green" id="infraCost">$0.00</span>
  </div>
</div>

<div class="grid">

  <div class="card full-width">
    <h2>Generate</h2>
    <label for="promptInput">Your Prompt</label>
    <textarea id="promptInput" rows="3"
      placeholder="Try: 'What is indemnification?' or 'Explain transformers' or 'Describe a binary search algorithm'"></textarea>

    <div class="form-row">
      <div>
        <label for="domainSelect">Adapter</label>
        <select id="domainSelect">
          <option value="auto">Auto-detect</option>
          <option value="adapter_1">Legal</option>
          <option value="adapter_2">Medical</option>
          <option value="adapter_3">Coding</option>
          <option value="none">Base Model (no adapter)</option>
        </select>
      </div>
      <div>
        <label>Max Tokens: <span id="tokensVal">512</span></label>
        <input type="range" id="maxTokens" min="64" max="2048" step="64" value="512"
          oninput="document.getElementById('tokensVal').textContent=this.value">
        <label style="margin-top:12px">Temperature: <span id="tempVal">0.7</span></label>
        <input type="range" id="temperature" min="0" max="1" step="0.1" value="0.7"
          oninput="document.getElementById('tempVal').textContent=this.value">
      </div>
    </div>
    <button class="btn-primary" id="generateBtn" onclick="doGenerate()">Generate</button>
    <div id="autoDetectBadge" style="display:none"></div>
    <div style="margin-top:16px">
      <label>Response</label>
      <div class="response-box empty" id="responseBox">Response will appear here...</div>
    </div>
    <div class="metrics-row" id="metricsRow" style="display:none">
      <div class="metric-box">
        <div class="metric-label">Input Type</div>
        <div class="metric-val purple" id="mInputType">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Adapter Used</div>
        <div class="metric-val" id="mAdapter">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Time to First Token</div>
        <div class="metric-val cyan" id="mTTFT">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Throughput</div>
        <div class="metric-val cyan" id="mTPS">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Generated Tokens</div>
        <div class="metric-val" id="mTokens">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Prompt Tokens</div>
        <div class="metric-val" id="mPromptTokens">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Total Latency</div>
        <div class="metric-val orange" id="mLatency">&mdash;</div>
      </div>
      <div class="metric-box">
        <div class="metric-label">Request Cost</div>
        <div class="metric-val green" id="mCost">&mdash;</div>
      </div>
    </div>
  </div>

  <div class="card" id="costCard">
    <h2>Live Infrastructure Cost</h2>
    <div class="cost-subtitle">
      SageMaker ml.g5.xlarge (A10G 24 GB) &middot; $1.41/hr &middot; Cost runs while endpoint is InService
    </div>

    <div class="cost-bars">
      <div class="cost-bar-row">
        <div class="cost-bar-header">
          <span>Multi-LoRA AWQ (this project) <span class="cost-bar-tag you">YOU</span></span>
          <span>$1.41/hr</span>
        </div>
        <div class="cost-bar-bg"><div class="cost-bar-fill bar-green" style="width:33.3%"></div></div>
      </div>
      <div class="cost-bar-row">
        <div class="cost-bar-header">
          <span>3x AWQ models (3 endpoints)</span>
          <span>$4.23/hr</span>
        </div>
        <div class="cost-bar-bg"><div class="cost-bar-fill bar-orange" style="width:100%"></div></div>
      </div>
    </div>

    <div class="cost-section-label">Projected (24/7 Operation)</div>
    <div class="cost-row">
      <span class="cost-row-label">Weekly</span>
      <span class="cost-row-value" id="projWeekly">$237 vs $710</span>
    </div>
    <div class="cost-row">
      <span class="cost-row-label">Monthly</span>
      <span class="cost-row-value" id="projMonthly">$1,015 vs $3,043</span>
    </div>
    <div class="cost-row">
      <span class="cost-row-label">Annual Savings</span>
      <span class="cost-row-value blue big" id="projAnnual">~$24,336</span>
    </div>

    <div id="costOnline" style="display:none">
      <div class="cost-section-label">This Session (live)</div>
      <div class="cost-row">
        <span class="cost-row-label">Endpoint Uptime</span>
        <span class="cost-row-value" id="sessionUptime">&mdash;</span>
      </div>
      <div class="cost-row">
        <span class="cost-row-label">Your Cost (Multi-LoRA)</span>
        <span class="cost-row-value green" id="sessionCostML">$0.00</span>
      </div>
      <div class="cost-row">
        <span class="cost-row-label">3-Model Equivalent</span>
        <span class="cost-row-value red" id="sessionCost3M">$0.00</span>
      </div>
      <div class="cost-row">
        <span class="cost-row-label">You Saved</span>
        <span class="cost-row-value blue big" id="sessionSaved">$0.00</span>
      </div>
    </div>

    <div id="costOffline" style="margin-top:12px">
      <div class="cost-offline">
        Endpoint is offline &middot; Session cost starts when you run python 4_deploy_endpoint.py
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Adapter Registry</h2>
    <table class="adapter-table">
      <thead>
        <tr><th>Adapter</th><th>Domain</th><th>Size</th><th>Status</th></tr>
      </thead>
      <tbody>
        <tr>
          <td><span class="tag tag-adapter1">Legal</span></td>
          <td>Contract law, liability</td>
          <td>~65 MB</td>
          <td><span class="tag tag-online">Loaded</span></td>
        </tr>
        <tr>
          <td><span class="tag tag-adapter2">Medical</span></td>
          <td>Pharmacology, clinical</td>
          <td>~65 MB</td>
          <td><span class="tag tag-online">Loaded</span></td>
        </tr>
        <tr>
          <td><span class="tag tag-adapter3">Coding</span></td>
          <td>Algorithms, programming</td>
          <td>~65 MB</td>
          <td><span class="tag tag-online">Loaded</span></td>
        </tr>
      </tbody>
    </table>
    <p style="margin-top:14px; font-size:0.78rem; color:#4a4d5a;">
      Base: Llama 3.1 8B AWQ + 3 LoRA adapters on ml.g5.xlarge (A10G 24 GB)
    </p>
  </div>

  <div class="card full-width">
    <h2>Request History</h2>
    <div class="history-wrap">
      <table class="history-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Adapter</th>
            <th>TTFT</th>
            <th>Throughput</th>
            <th>Latency</th>
            <th>Tokens</th>
            <th>Cost</th>
            <th>Prompt</th>
          </tr>
        </thead>
        <tbody id="historyBody">
          <tr><td colspan="8" class="empty-history">No requests yet. Try a prompt above.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
const API_URL = "{api_url}";
const API_KEY = "{api_key}";

const ML_RATE  = 1.41;
const TM_RATE  = 4.23;

let history = [];
let endpointStart = null;
let costTickerId = null;

function apiHeaders() {{
  return {{ "Content-Type": "application/json", "x-api-key": API_KEY }};
}}

async function checkHealth() {{
  try {{
    var r = await fetch(API_URL + "/health", {{ headers: apiHeaders() }});
    var d = await r.json();
    var dot = document.getElementById("endpointDot");
    var st  = document.getElementById("endpointStatus");
    if (d.ready === true) {{
      dot.className = "dot green";
      st.textContent = "InService";
      if (d.creation_time) {{
        endpointStart = new Date(d.creation_time);
      }}
      document.getElementById("costOnline").style.display = "block";
      document.getElementById("costOffline").style.display = "none";
      if (!costTickerId) {{
        costTickerId = setInterval(updateCostTracker, 1000);
        updateCostTracker();
      }}
    }} else {{
      dot.className = "dot red";
      var smap = {{"NotFound":"Offline","Creating":"Starting...","Updating":"Updating...","Deleting":"Shutting down...","Failed":"Failed"}};
      st.textContent = smap[d.endpoint_status] || d.endpoint_status || "Offline";
      endpointStart = null;
      document.getElementById("costOnline").style.display = "none";
      document.getElementById("costOffline").style.display = "block";
      document.getElementById("infraCost").textContent = "$0.00";
      if (costTickerId) {{ clearInterval(costTickerId); costTickerId = null; }}
    }}
  }} catch(e) {{
    document.getElementById("endpointStatus").textContent = "Unreachable";
    document.getElementById("infraCost").textContent = "$0.00";
  }}
}}

function updateCostTracker() {{
  if (!endpointStart) return;
  var ms = Date.now() - endpointStart.getTime();
  var hrs = ms / 3600000;
  var mins = Math.floor(ms / 60000);
  var mlCost = hrs * ML_RATE;
  var tmCost = hrs * TM_RATE;
  var saved  = tmCost - mlCost;
  var pct    = tmCost > 0 ? Math.round((saved / tmCost) * 100) : 69;
  document.getElementById("sessionUptime").textContent  = mins + " min";
  document.getElementById("sessionCostML").textContent   = "$" + mlCost.toFixed(2);
  document.getElementById("sessionCost3M").textContent   = "$" + tmCost.toFixed(2);
  document.getElementById("sessionSaved").textContent    = "$" + saved.toFixed(2) + " (" + pct + "%)";
  document.getElementById("infraCost").textContent = "$" + mlCost.toFixed(2);
}}

async function loadMetrics() {{
  try {{
    var r = await fetch(API_URL + "/metrics", {{ headers: apiHeaders() }});
    var d = await r.json();
    document.getElementById("totalReqs").textContent = d.total_requests || 0;
    document.getElementById("avgTTFT").textContent =
      d.avg_ttft_ms ? Math.round(d.avg_ttft_ms) + "ms" : "\\u2014";
    document.getElementById("avgTPS").textContent =
      d.avg_tokens_per_second ? d.avg_tokens_per_second.toFixed(1) + " tok/s" : "\\u2014";
  }} catch(e) {{}}
}}

async function doGenerate() {{
  var prompt = document.getElementById("promptInput").value.trim();
  if (!prompt) return;

  var btn = document.getElementById("generateBtn");
  var box = document.getElementById("responseBox");
  var badge = document.getElementById("autoDetectBadge");
  var mRow = document.getElementById("metricsRow");

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Generating...';
  box.className = "response-box loading";
  box.textContent = "Routing to adapter and generating...";
  badge.style.display = "none";
  mRow.style.display = "none";

  var payload = {{
    prompt: prompt,
    domain: document.getElementById("domainSelect").value,
    max_tokens: parseInt(document.getElementById("maxTokens").value),
    temperature: parseFloat(document.getElementById("temperature").value),
  }};

  try {{
    var r = await fetch(API_URL + "/generate", {{
      method: "POST", headers: apiHeaders(), body: JSON.stringify(payload),
    }});
    var d = await r.json();

    if (!r.ok) {{
      box.className = "response-box error";
      if (r.status === 503 || (d.error && d.error.includes("offline"))) {{
        box.textContent =
          "SageMaker endpoint is offline.\\n\\n" +
          "Run: python 4_deploy_endpoint.py\\n\\n" +
          "The endpoint only runs during demo sessions to save cost (~$1.41/hr).\\n" +
          "It takes ~15 minutes to start.";
      }} else {{
        box.textContent = "Error " + r.status + ": " + (d.error || d.detail || JSON.stringify(d));
      }}
      return;
    }}

    box.className = "response-box";
    box.textContent = d.response;

    var adapterNames = {{"adapter_1":"Legal","adapter_2":"Medical","adapter_3":"Coding","base_model":"Base Model"}};
    var badges = "";
    if (payload.domain === "auto") {{
      badges += '<span class="badge">Auto-detected: ' + (adapterNames[d.domain_detected] || d.domain_detected || "none") + '</span> ';
    }}
    if (badges) {{
      badge.style.display = "block";
      badge.innerHTML = badges;
    }}

    mRow.style.display = "grid";
    document.getElementById("mInputType").textContent  = "Text";
    document.getElementById("mAdapter").textContent    = adapterNames[d.adapter_used] || (d.adapter_used || "base_model").replace("_", " ");
    document.getElementById("mTTFT").textContent       = Math.round(d.ttft_ms || 0) + "ms";
    document.getElementById("mTPS").textContent        = (d.tokens_per_second || 0).toFixed(1) + " tok/s";
    document.getElementById("mTokens").textContent     = d.tokens_generated || 0;
    document.getElementById("mPromptTokens").textContent = d.prompt_tokens || 0;
    document.getElementById("mLatency").textContent    = Math.round(d.latency_ms) + "ms";
    document.getElementById("mCost").textContent       = "$" + (d.estimated_cost_usd || 0).toFixed(6);

    var tagClass = {{"adapter_1":"tag-adapter1","adapter_2":"tag-adapter2","adapter_3":"tag-adapter3"}}[d.domain_detected] || "tag-base";
    history.unshift({{
      time: new Date().toLocaleTimeString(),
      adapter: adapterNames[d.adapter_used] || d.adapter_used || "base_model",
      tagClass: tagClass,
      ttft: Math.round(d.ttft_ms || 0) + "ms",
      tps: (d.tokens_per_second || 0).toFixed(1) + " tok/s",
      latency: Math.round(d.latency_ms) + "ms",
      tokens: d.tokens_generated || 0,
      cost: "$" + (d.estimated_cost_usd || 0).toFixed(6),
      preview: prompt.length > 35 ? prompt.slice(0, 35) + "..." : prompt,
    }});
    if (history.length > 20) history.pop();
    renderHistory();
    loadMetrics();

  }} catch(e) {{
    box.className = "response-box error";
    box.textContent =
      "Cannot reach API.\\n\\nMake sure the Lambda is deployed:\\n" +
      "python 1_deploy_lambda.py\\n\\nError: " + e.message;
  }} finally {{
    btn.disabled = false;
    btn.textContent = "Generate";
  }}
}}

function renderHistory() {{
  var tb = document.getElementById("historyBody");
  if (history.length === 0) {{
    tb.innerHTML = '<tr><td colspan="8" class="empty-history">No requests yet.</td></tr>';
    return;
  }}
  tb.innerHTML = history.map(function(h) {{
    return '<tr>' +
      '<td>' + h.time + '</td>' +
      '<td><span class="tag ' + h.tagClass + '">' + h.adapter + '</span></td>' +
      '<td>' + h.ttft + '</td>' +
      '<td>' + h.tps + '</td>' +
      '<td>' + h.latency + '</td>' +
      '<td>' + h.tokens + '</td>' +
      '<td>' + h.cost + '</td>' +
      '<td style="color:#8b8fa8;max-width:180px;overflow:hidden;text-overflow:ellipsis">' + h.preview + '</td>' +
    '</tr>';
  }}).join("");
}}

document.addEventListener("DOMContentLoaded", function() {{
  document.getElementById("promptInput").addEventListener("keydown", function(e) {{
    if (e.ctrlKey && e.key === "Enter") doGenerate();
  }});

  checkHealth();
  loadMetrics();
  setInterval(function() {{ checkHealth(); loadMetrics(); }}, 30000);
}});
</script>
</body>
</html>"""
