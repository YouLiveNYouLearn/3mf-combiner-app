"""
Bambu Lab .gcode.3mf Queue Builder
====================================
Literal concatenation mode.
Each uploaded .gcode.3mf is treated as a complete self-contained job.
The full embedded G-code from each file is appended in order — repeated
as many times as requested — with no splitting, merging, or injection.

Run with:  python3 app.py
Then open: http://127.0.0.1:5000
"""

import io
import json
import os
import zipfile
from flask import Flask, request, jsonify, send_file, render_template_string

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # 512 MB upload limit


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------

def find_gcode_entry(zf: zipfile.ZipFile) -> str:
    """Return the path of the embedded .gcode file inside a .gcode.3mf archive."""
    for name in zf.namelist():
        if name.lower().endswith(".gcode"):
            return name
    raise ValueError(
        "No .gcode file found inside the .gcode.3mf archive. "
        "Make sure you exported a plate file from Bambu Studio."
    )


def concatenate_jobs(job_gcodes: list[str]) -> str:
    """
    Concatenate the full G-code text of each job in order.
    No splitting, no injection, no modification — pure concatenation.
    A single blank line separates each job for readability.
    """
    return "\n\n".join(job_gcodes)


# ---------------------------------------------------------------------------
# HTML / CSS / JS  (single-page, inline)
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Bambu Queue Builder</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:      #0d0f14;
    --surface: #13161d;
    --panel:   #1a1e28;
    --border:  #252a38;
    --accent:  #00e5a0;
    --accent2: #005eff;
    --warn:    #ff6b35;
    --warn2:   #f5c518;
    --text:    #e8eaf0;
    --muted:   #6b7280;
    --radius:  10px;
    --mono:    'DM Mono', monospace;
    --sans:    'Syne', sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--sans); min-height: 100vh; padding: 0 0 80px; }

  /* ── Header ── */
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 40px; display: flex; align-items: center; gap: 16px; position: sticky; top: 0; z-index: 100; backdrop-filter: blur(12px); }
  .logo-pill { background: var(--accent); color: #000; font-weight: 800; font-size: 11px; letter-spacing: .12em; padding: 4px 10px; border-radius: 4px; text-transform: uppercase; }
  header h1 { font-size: 18px; font-weight: 700; }
  header p  { font-size: 13px; color: var(--muted); margin-left: auto; font-family: var(--mono); }

  /* ── Layout ── */
  main { max-width: 860px; margin: 0 auto; padding: 40px 24px 0; }
  section { margin-bottom: 36px; }
  section > h2 { font-size: 11px; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--accent); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
  section > h2::after { content: ''; flex: 1; height: 1px; background: var(--border); }
  .step-badge { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--accent2); color: #fff; font-size: 11px; font-weight: 700; flex-shrink: 0; }

  /* ── Info / warning boxes ── */
  .info-box {
    background: rgba(0,229,160,.05);
    border: 1px solid rgba(0,229,160,.2);
    border-radius: var(--radius);
    padding: 14px 16px;
    font-size: 12px;
    font-family: var(--mono);
    color: #a0f0d8;
    line-height: 1.7;
  }
  .info-box strong { color: var(--accent); }

  .warn-box {
    background: rgba(255,107,53,.07);
    border: 1px solid rgba(255,107,53,.28);
    border-radius: var(--radius);
    padding: 14px 16px;
    font-size: 12px;
    font-family: var(--mono);
    color: #ffaa80;
    line-height: 1.7;
  }
  .warn-box strong { color: var(--warn); }

  /* ── Drop zone ── */
  #dropzone { border: 2px dashed var(--border); border-radius: var(--radius); padding: 48px 24px; text-align: center; cursor: pointer; transition: border-color .2s, background .2s; background: var(--surface); position: relative; }
  #dropzone.drag-over { border-color: var(--accent); background: rgba(0,229,160,.05); }
  #dropzone input[type=file] { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%; }
  #dropzone .dz-icon  { font-size: 36px; margin-bottom: 12px; display: block; }
  #dropzone .dz-title { font-size: 16px; font-weight: 700; margin-bottom: 6px; }
  #dropzone .dz-sub   { font-size: 13px; color: var(--muted); font-family: var(--mono); }

  /* ── File list ── */
  #file-list { display: flex; flex-direction: column; gap: 10px; }
  #file-list:empty::after { content: 'No files added yet.'; color: var(--muted); font-size: 13px; font-family: var(--mono); display: block; text-align: center; padding: 20px; }
  .file-card { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; display: grid; grid-template-columns: 24px 1fr auto auto auto; align-items: center; gap: 12px; transition: border-color .15s, box-shadow .15s; cursor: grab; }
  .file-card:active { cursor: grabbing; }
  .file-card.drag-target { border-color: var(--accent2); box-shadow: 0 0 0 2px rgba(0,94,255,.25); }
  .drag-handle { color: var(--muted); font-size: 16px; cursor: grab; user-select: none; }
  .file-info { min-width: 0; }
  .file-name { font-family: var(--mono); font-size: 12px; color: var(--accent); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px; }
  .file-label-wrap { display: flex; align-items: center; gap: 6px; }
  .file-label-wrap label { font-size: 11px; color: var(--muted); white-space: nowrap; }
  .file-label-wrap input[type=text] { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: var(--mono); font-size: 12px; padding: 4px 8px; width: 160px; transition: border-color .15s; }
  .file-label-wrap input[type=text]:focus { outline: none; border-color: var(--accent); }
  .copies-wrap { display: flex; flex-direction: column; align-items: center; gap: 4px; }
  .copies-wrap label { font-size: 10px; color: var(--muted); letter-spacing: .06em; text-transform: uppercase; }
  .copies-input { background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); font-family: var(--mono); font-size: 14px; font-weight: 600; width: 60px; text-align: center; padding: 4px; -moz-appearance: textfield; transition: border-color .15s; }
  .copies-input::-webkit-outer-spin-button, .copies-input::-webkit-inner-spin-button { -webkit-appearance: none; }
  .copies-input:focus { outline: none; border-color: var(--accent); }
  .move-btns { display: flex; flex-direction: column; gap: 4px; }
  .move-btns button { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 5px; width: 28px; height: 24px; cursor: pointer; font-size: 12px; display: flex; align-items: center; justify-content: center; transition: border-color .15s, color .15s; }
  .move-btns button:hover { border-color: var(--accent); color: var(--accent); }
  .remove-btn { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 16px; padding: 4px; border-radius: 5px; transition: color .15s; line-height: 1; }
  .remove-btn:hover { color: var(--warn); }

  /* ── Queue summary ── */
  #queue-summary { font-size: 12px; font-family: var(--mono); color: var(--muted); margin-top: 10px; min-height: 18px; }
  #queue-summary span { color: var(--accent); font-weight: 600; }

  /* ── Generate ── */
  #generate-btn { display: block; width: 100%; padding: 18px; background: var(--accent); color: #000; border: none; border-radius: var(--radius); font-family: var(--sans); font-size: 16px; font-weight: 800; letter-spacing: .04em; cursor: pointer; transition: background .15s, transform .1s, box-shadow .15s; box-shadow: 0 4px 24px rgba(0,229,160,.25); }
  #generate-btn:hover { background: #00ffa8; box-shadow: 0 6px 32px rgba(0,229,160,.4); }
  #generate-btn:active { transform: scale(.99); }
  #generate-btn:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; box-shadow: none; }

  /* ── Print success widget ── */
  #print-success-wrap { display: none; margin-top: 20px; background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 20px; flex-direction: column; gap: 12px; }
  #print-success-wrap.visible { display: flex; }
  .success-q { font-size: 13px; font-weight: 600; color: var(--text); }
  .success-btns { display: flex; gap: 8px; flex-wrap: wrap; }
  .success-btn { background: var(--bg); border: 1px solid var(--border); color: var(--muted); border-radius: 7px; font-family: var(--sans); font-size: 12px; font-weight: 700; padding: 6px 16px; cursor: pointer; transition: all .15s; }
  .success-btn:hover { border-color: var(--accent2); color: var(--text); }
  .success-btn.yes:hover { border-color: var(--accent); color: var(--accent); }
  .success-btn.no:hover  { border-color: var(--warn);   color: var(--warn); }
  .success-thanks { font-size: 12px; font-family: var(--mono); color: var(--accent); display: none; }
  .success-thanks.show { display: block; }

  /* ── Toast ── */
  #toast { position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%) translateY(20px); background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 22px; font-size: 14px; font-family: var(--mono); max-width: 500px; text-align: center; opacity: 0; transition: opacity .25s, transform .25s; z-index: 999; pointer-events: none; }
  #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
  #toast.error   { border-color: var(--warn);   color: var(--warn); }
  #toast.success { border-color: var(--accent);  color: var(--accent); }
  #toast.info    { border-color: var(--accent2); color: #6faeff; }

  /* ── Spinner ── */
  #spinner { display: none; position: fixed; inset: 0; background: rgba(13,15,20,.7); backdrop-filter: blur(4px); z-index: 200; align-items: center; justify-content: center; flex-direction: column; gap: 16px; }
  #spinner.show { display: flex; }
  .spin-ring { width: 48px; height: 48px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .7s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  #spinner p { font-family: var(--mono); font-size: 13px; color: var(--muted); }

  /* ── Feedback section ── */
  #feedback-section { max-width: 860px; margin: 0 auto; padding: 0 24px 40px; }
  #feedback-section h2 { font-size: 11px; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; display: flex; align-items: center; gap: 8px; }
  #feedback-section h2::after { content: ''; flex: 1; height: 1px; background: var(--border); }
  .feedback-desc { font-size: 12px; font-family: var(--mono); color: var(--muted); margin-bottom: 16px; line-height: 1.5; }
  .feedback-form { background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  .fb-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  @media (max-width: 600px) { .fb-row { grid-template-columns: 1fr; } }
  .fb-field { display: flex; flex-direction: column; gap: 6px; }
  .fb-field label { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
  .fb-field input, .fb-field select, .fb-field textarea { background: var(--bg); border: 1px solid var(--border); border-radius: 7px; color: var(--text); font-family: var(--mono); font-size: 12px; padding: 8px 10px; transition: border-color .15s; }
  .fb-field input:focus, .fb-field select:focus, .fb-field textarea:focus { outline: none; border-color: var(--accent2); }
  .fb-field textarea { resize: vertical; min-height: 90px; line-height: 1.6; }
  .fb-field select option { background: var(--panel); }
  #fb-submit { align-self: flex-start; background: var(--bg); border: 1px solid var(--accent2); color: var(--accent2); border-radius: 7px; font-family: var(--sans); font-size: 12px; font-weight: 700; padding: 8px 20px; cursor: pointer; transition: background .15s, color .15s; }
  #fb-submit:hover { background: var(--accent2); color: #fff; }
  #fb-submit:disabled { opacity: .4; cursor: not-allowed; }
  #fb-thanks { display: none; font-size: 12px; font-family: var(--mono); color: var(--accent); padding: 8px 0; }
  #fb-thanks.show { display: block; }

  /* ── Footer ── */
  footer { border-top: 1px solid var(--border); padding: 20px 24px; text-align: center; font-size: 11px; font-family: var(--mono); color: #3d4455; line-height: 1.7; margin-top: 20px; }
</style>
</head>
<body>

<header>
  <span class="logo-pill">Bambu</span>
  <h1>Queue Builder</h1>
  <p>.gcode.3mf queue combiner</p>
</header>

<main>

  <!-- How this works -->
  <section>
    <h2><span class="step-badge" style="background:var(--muted)">ℹ</span> How this works</h2>
    <div class="info-box">
      <strong>Literal concatenation mode.</strong> Each uploaded <code>.gcode.3mf</code> is treated as a
      complete, self-contained job. The full embedded G-code from each file is appended in order —
      repeated as many times as you request — with <strong>nothing added, removed, or modified</strong>.<br><br>
      All printer startup, homing, heating, printing, cooldown, and shutdown behavior is preserved
      exactly as baked into each uploaded file by Bambu Studio.
    </div>
    <br>
    <div class="warn-box">
      <strong>⚠️ Before you print:</strong><br>
      • Make sure every uploaded file was sliced correctly for your printer and workflow.<br>
      • Startup and shutdown G-code (homing, heating, push-off, fan cooldown, etc.) will run
        in full for <em>every repeated job</em>, exactly as it exists in each uploaded file.<br>
      • Always verify the output on your printer before leaving it unattended.
    </div>
  </section>

  <!-- STEP 1: Upload -->
  <section>
    <h2><span class="step-badge">1</span> Upload plate files</h2>
    <div id="dropzone">
      <input type="file" id="file-input" accept=".3mf" multiple/>
      <span class="dz-icon">📂</span>
      <div class="dz-title">Drop .gcode.3mf files here</div>
      <div class="dz-sub">or click to browse &nbsp;·&nbsp; multiple files OK</div>
    </div>
  </section>

  <!-- STEP 2: Order & copies -->
  <section>
    <h2><span class="step-badge">2</span> Set order, labels &amp; copies</h2>
    <div id="file-list"></div>
    <div id="queue-summary"></div>
  </section>

  <!-- STEP 3: Generate -->
  <section>
    <h2><span class="step-badge">3</span> Generate queue file</h2>
    <button id="generate-btn">⚡ Generate combined .gcode.3mf</button>
    <div id="print-success-wrap">
      <div class="success-q">Did this combined file print successfully?</div>
      <div class="success-btns">
        <button class="success-btn yes" data-val="Yes">✅ Yes</button>
        <button class="success-btn"     data-val="Partially">⚠️ Partially</button>
        <button class="success-btn no"  data-val="No">❌ No</button>
      </div>
      <div class="success-thanks" id="success-thanks">Thanks — that helps validate the tool.</div>
    </div>
  </section>

</main>

<!-- Feedback section -->
<div id="feedback-section">
  <h2>Suggest a feature or report an issue</h2>
  <p class="feedback-desc">Help improve this tool. What would you like to see added or fixed?</p>
  <div class="feedback-form">
    <div class="fb-row">
      <div class="fb-field">
        <label>Type <span style="color:var(--warn);font-size:10px;">required</span></label>
        <select id="fb-type">
          <option value="">— select —</option>
          <option value="Feature request">Feature request</option>
          <option value="Bug report">Bug report</option>
          <option value="Preset request">Preset request</option>
          <option value="Other">Other</option>
        </select>
      </div>
      <div class="fb-field">
        <label>Printer model <span style="color:var(--muted);font-size:10px;">optional</span></label>
        <input type="text" id="fb-printer" placeholder="e.g. A1 Mini, P1S, X1C"/>
      </div>
    </div>
    <div class="fb-field">
      <label>Your feedback <span style="color:var(--warn);font-size:10px;">required</span></label>
      <textarea id="fb-message" placeholder="Describe your idea, issue, or request…"></textarea>
    </div>
    <div class="fb-field">
      <label>Email <span style="color:var(--muted);font-size:10px;">optional — if you'd like a response</span></label>
      <input type="email" id="fb-email" placeholder="If you'd like a response"/>
    </div>
    <button id="fb-submit">Submit feedback</button>
    <div id="fb-thanks">Thanks — your feedback helps improve this tool.</div>
  </div>
</div>

<footer>
  © 2026 Bambu Queue Builder. Built with AI assistance.<br>
  Always verify generated G-code before printing. Use at your own risk.
</footer>

<div id="spinner"><div class="spin-ring"></div><p>Building your queue file…</p></div>
<div id="toast"></div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let files     = [];
let idCounter = 0;

// ── Toast ──────────────────────────────────────────────────────────────────
let toastTimer;
function showToast(msg, type = 'info') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.className = '', 4500);
}

// ── Queue summary ──────────────────────────────────────────────────────────
function updateSummary() {
  const el = document.getElementById('queue-summary');
  if (files.length === 0) { el.textContent = ''; return; }
  const total = files.reduce((s, f) => s + f.copies, 0);
  const unique = files.length;
  el.innerHTML = `Queue: <span>${unique}</span> file${unique !== 1 ? 's' : ''} · <span>${total}</span> total job${total !== 1 ? 's' : ''} in output`;
}

// ── Drop zone ──────────────────────────────────────────────────────────────
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');

dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag-over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag-over'));
dropzone.addEventListener('drop', e => { e.preventDefault(); dropzone.classList.remove('drag-over'); addFiles(e.dataTransfer.files); });
fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });

function addFiles(fileList) {
  const bad = [];
  [...fileList].forEach(f => {
    if (!f.name.endsWith('.3mf')) { bad.push(f.name); return; }
    files.push({ id: ++idCounter, name: f.name, file: f, label: f.name.replace(/\.gcode\.3mf$|\.3mf$/i, ''), copies: 1 });
  });
  if (bad.length) showToast('Skipped (not .3mf): ' + bad.join(', '), 'error');
  renderList();
}

// ── Render file list ────────────────────────────────────────────────────────
function renderList() {
  const list = document.getElementById('file-list');
  list.innerHTML = '';

  files.forEach((f, i) => {
    const card = document.createElement('div');
    card.className = 'file-card';
    card.draggable = true;
    card.dataset.id = f.id;
    card.innerHTML = `
      <span class="drag-handle" title="Drag to reorder">⠿</span>
      <div class="file-info">
        <div class="file-name" title="${esc(f.name)}">${esc(f.name)}</div>
        <div class="file-label-wrap">
          <label for="lbl-${f.id}">Label:</label>
          <input type="text" id="lbl-${f.id}" value="${esc(f.label)}" data-id="${f.id}" class="label-input" placeholder="Friendly name"/>
        </div>
      </div>
      <div class="copies-wrap">
        <label>Copies</label>
        <input type="number" class="copies-input" data-id="${f.id}" value="${f.copies}" min="1" max="99"/>
      </div>
      <div class="move-btns">
        <button data-dir="up"   data-id="${f.id}" ${i === 0 ? 'disabled' : ''}>▲</button>
        <button data-dir="down" data-id="${f.id}" ${i === files.length - 1 ? 'disabled' : ''}>▼</button>
      </div>
      <button class="remove-btn" data-id="${f.id}" title="Remove">✕</button>`;
    list.appendChild(card);
  });

  list.querySelectorAll('.label-input').forEach(inp =>
    inp.addEventListener('input', () => {
      const e = files.find(x => x.id == inp.dataset.id);
      if (e) e.label = inp.value;
    }));

  list.querySelectorAll('.copies-input').forEach(inp =>
    inp.addEventListener('input', () => {
      const e = files.find(x => x.id == inp.dataset.id);
      if (e) { e.copies = Math.max(1, parseInt(inp.value) || 1); updateSummary(); }
    }));

  list.querySelectorAll('.move-btns button').forEach(btn =>
    btn.addEventListener('click', () => {
      const idx = files.findIndex(x => x.id == btn.dataset.id);
      const dir = btn.dataset.dir === 'up' ? -1 : 1;
      if (idx + dir < 0 || idx + dir >= files.length) return;
      [files[idx], files[idx + dir]] = [files[idx + dir], files[idx]];
      renderList();
    }));

  list.querySelectorAll('.remove-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      files = files.filter(x => x.id != btn.dataset.id);
      renderList();
    }));

  // Drag-and-drop reorder
  let dragSrc = null;
  list.querySelectorAll('.file-card').forEach(card => {
    card.addEventListener('dragstart', () => { dragSrc = card; card.style.opacity = '.4'; });
    card.addEventListener('dragend',   () => {
      dragSrc.style.opacity = '';
      list.querySelectorAll('.file-card').forEach(c => c.classList.remove('drag-target'));
    });
    card.addEventListener('dragover',  e => { e.preventDefault(); if (card !== dragSrc) card.classList.add('drag-target'); });
    card.addEventListener('dragleave', () => card.classList.remove('drag-target'));
    card.addEventListener('drop', e => {
      e.preventDefault();
      if (!dragSrc || dragSrc === card) return;
      const si = files.findIndex(x => x.id === parseInt(dragSrc.dataset.id));
      const di = files.findIndex(x => x.id === parseInt(card.dataset.id));
      files.splice(di, 0, files.splice(si, 1)[0]);
      renderList();
    });
  });

  updateSummary();
}

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Generate ───────────────────────────────────────────────────────────────
document.getElementById('generate-btn').addEventListener('click', async () => {
  if (files.length === 0) { showToast('Please upload at least one .gcode.3mf file.', 'error'); return; }

  const btn = document.getElementById('generate-btn');
  btn.disabled = true;
  document.getElementById('spinner').classList.add('show');

  try {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f.file, f.name));
    fd.append('meta', JSON.stringify(files.map(f => ({ name: f.name, label: f.label, copies: f.copies }))));

    const resp = await fetch('/generate', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json();
      showToast('Error: ' + (err.error || 'Unknown error'), 'error');
      return;
    }

    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'combined_queue.gcode.3mf'; a.click();
    URL.revokeObjectURL(url);
    showToast('Queue file generated and downloaded!', 'success');

    const psw = document.getElementById('print-success-wrap');
    psw.classList.add('visible');
    document.getElementById('success-thanks').classList.remove('show');
    psw.querySelectorAll('.success-btn').forEach(b => b.disabled = false);

  } catch (e) {
    showToast('Unexpected error: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    document.getElementById('spinner').classList.remove('show');
  }
});

// ── Print success widget ───────────────────────────────────────────────────
document.querySelectorAll('.success-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    const val = btn.dataset.val;
    document.querySelectorAll('.success-btn').forEach(b => b.disabled = true);
    document.getElementById('success-thanks').classList.add('show');
    try {
      await fetch('/log_print_result', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ result: val })
      });
    } catch (e) { /* silent — best-effort */ }
  });
});

// ── Feedback form ──────────────────────────────────────────────────────────
document.getElementById('fb-submit').addEventListener('click', async () => {
  const type    = document.getElementById('fb-type').value.trim();
  const message = document.getElementById('fb-message').value.trim();
  if (!type)    { showToast('Please select a feedback type.', 'error');    return; }
  if (!message) { showToast('Please enter your feedback message.', 'error'); return; }

  const payload = {
    type, message,
    printer: document.getElementById('fb-printer').value.trim() || '(not specified)',
    email:   document.getElementById('fb-email').value.trim()   || '(not provided)',
  };
  const btn = document.getElementById('fb-submit');
  btn.disabled = true;
  try {
    const resp = await fetch('/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (resp.ok) {
      document.getElementById('fb-thanks').classList.add('show');
      ['fb-type', 'fb-printer', 'fb-message', 'fb-email'].forEach(id => document.getElementById(id).value = '');
      setTimeout(() => document.getElementById('fb-thanks').classList.remove('show'), 6000);
    } else {
      showToast('Could not submit feedback. Please try again.', 'error');
      btn.disabled = false;
    }
  } catch (e) {
    showToast('Could not submit feedback — server error.', 'error');
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/generate", methods=["POST"])
def generate():
    uploaded = request.files.getlist("files")
    if not uploaded or all(f.filename == "" for f in uploaded):
        return jsonify(error="No files uploaded."), 400

    try:
        meta = json.loads(request.form.get("meta", "[]"))
    except json.JSONDecodeError:
        return jsonify(error="Invalid metadata; please reload and try again."), 400

    if len(uploaded) != len(meta):
        return jsonify(error=f"File count mismatch ({len(uploaded)} files, {len(meta)} metadata entries)."), 400

    # ── Extract full G-code from each file and expand by copy count ──────────
    job_gcodes             = []   # full G-code strings, in final queue order
    template_zip_bytes     = None
    template_gcode_name    = None

    for i, (uf, m) in enumerate(zip(uploaded, meta)):
        copies = max(1, int(m.get("copies", 1)))
        raw    = uf.read()

        if not raw:
            return jsonify(error=f"File '{uf.filename}' appears to be empty."), 400

        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                gcode_name = find_gcode_entry(zf)
                gcode_text = zf.read(gcode_name).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            return jsonify(error=f"'{uf.filename}' is not a valid zip / .3mf archive."), 400
        except ValueError as e:
            return jsonify(error=str(e)), 400

        # Save the first archive as the output template
        if i == 0:
            template_zip_bytes  = raw
            template_gcode_name = gcode_name

        # Append full G-code, repeated exactly `copies` times
        for _ in range(copies):
            job_gcodes.append(gcode_text)

    # ── Concatenate — no splitting, no injection, no modification ────────────
    combined = concatenate_jobs(job_gcodes)

    # ── Rebuild archive: swap only the .gcode entry ──────────────────────────
    out_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template_zip_bytes)) as src_zf:
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as dst_zf:
            for item in src_zf.infolist():
                if item.filename == template_gcode_name:
                    dst_zf.writestr(item, combined.encode("utf-8"))
                else:
                    dst_zf.writestr(item, src_zf.read(item.filename))

    out_buf.seek(0)
    return send_file(
        out_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="combined_queue.gcode.3mf"
    )


@app.route("/feedback", methods=["POST"])
def feedback():
    """Prints user feedback to the server console. No storage."""
    data = request.get_json(silent=True) or {}
    print()
    print("=" * 50)
    print("[FEEDBACK]")
    print(f"  Type:    {data.get('type',    '(none)')}")
    print(f"  Printer: {data.get('printer', '(not specified)')}")
    print(f"  Message: {data.get('message', '(empty)')}")
    print(f"  Email:   {data.get('email',   '(not provided)')}")
    print("=" * 50)
    print()
    return jsonify(ok=True)


@app.route("/log_print_result", methods=["POST"])
def log_print_result():
    """Logs print success report to the console. No storage."""
    data = request.get_json(silent=True) or {}
    print()
    print(f"[PRINT RESULT] User reported: {data.get('result', '(unknown)')}")
    print()
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print()
    print("=" * 55)
    print("  Bambu Queue Builder is running!")
    print(f"  Open: http://127.0.0.1:{port}")
    print("  Press Ctrl+C to stop.")
    print("=" * 55)
    print()
    app.run(debug=False, host="0.0.0.0", port=port)
