import os
import re
from playwright.sync_api import sync_playwright

def parse_markdown_to_html(md_content):
    # 1. Multi-line LaTeX environments (\begin{cases} ... \end{cases})
    def multiline_math_repl(m):
        code = m.group(1).strip().replace('\n', ' ')
        return f'\n<div class="math-display">$${code}$$</div>\n'

    md_content = re.sub(
        r'\$\$(\s*[\s\S]*?\\begin\{[a-zA-Z*]+\}[\s\S]*?\\end\{[a-zA-Z*]+\}[\s\S]*?)\$\$',
        multiline_math_repl,
        md_content
    )

    # 2. Single-line display math $$ ... $$
    def singleline_math_repl(m):
        code = m.group(1).strip()
        return f'\n<div class="math-display">$${code}$$</div>\n'

    md_content = re.sub(r'\$\$([^\n]+?)\$\$', singleline_math_repl, md_content)

    # 3. Convert markdown links [text](url) or [`code`](url) before line splitting
    def link_repl(match):
        text = match.group(1)
        url = match.group(2)
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        return f'<a href="{url}" class="report-link">{text}</a>'
    
    md_content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link_repl, md_content)

    # 4. Custom Diagram & Card Templates

    at_a_glance_html = """
    <div class="card-container page-break-inside-avoid">
        <div class="card-header">
            <h3><span class="badge badge-primary">SUMMARY</span> PNMF Evaluation At a Glance</h3>
        </div>
        <table class="styled-table">
            <thead>
                <tr>
                    <th style="width: 22%;">Dimension</th>
                    <th style="width: 35%;">ECAC Doc 29 5th Edition Standard</th>
                    <th style="width: 25%;">PNMF Implementation (<code>projects/pnmf</code>)</th>
                    <th style="width: 18%;">Verdict</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>NPD Grid &amp; Format</strong></td>
                    <td>10 slant distances (200-25,000 ft), 4 metrics (SEL, LAmax, EPNL, PNLTM)</td>
                    <td>Strict EASA ANP layout exported via <code>NoisePrediction.to_anp_csv()</code></td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Distance Interpolation</strong></td>
                    <td>Linear in $\\log_{10}(d)$ within [200, 25k] ft; linear slope log-distance extrap</td>
                    <td><code>NPDTable.level()</code> via <code>_extrap_low</code> and <code>_extrap_high</code></td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Distance Monotonicity</strong></td>
                    <td>Physical sound levels must non-increase with distance</td>
                    <td>Enforced via <code>IsotonicRegression</code> in <code>enforce_distance_monotone()</code></td>
                    <td><span class="badge badge-star">SUPERIOR / EXCEEDS</span></td>
                </tr>
                <tr>
                    <td><strong>Power Parameter Units</strong></td>
                    <td>Raw ANP database mixes thrust (lb), % max static thrust, and RPM</td>
                    <td>Standardized via <code>power_features()</code> to $P_{\\text{lb}}$ and throttle fraction</td>
                    <td><span class="badge badge-star">SUPERIOR / EXCEEDS</span></td>
                </tr>
                <tr>
                    <td><strong>Trajectory Synthesis</strong></td>
                    <td>App B / SAE-AIR-1845 procedural steps (thrust rating $F_n/\\delta$, $S_g$, climb)</td>
                    <td><code>DepartureSynthesizer</code> for 142 aircraft; borrowed procedure scaling</td>
                    <td><span class="badge badge-info">SUBSTANTIALLY COMPLIANT</span></td>
                </tr>
                <tr>
                    <td><strong>Component Physics Scope</strong></td>
                    <td>Evaluates source emissions across metrics (SEL, LAmax, EPNL, PNLTM)</td>
                    <td><code>PhysicsNPDModel</code> covers 1/3-octave SEL &amp; LAmax; EPNL/PNLTM tones absent</td>
                    <td><span class="badge badge-warning">PARTIAL / LIMITATION</span></td>
                </tr>
                <tr>
                    <td><strong>Downstream Propagation</strong></td>
                    <td>Lateral attenuation, ground effect, and finite segment corrections</td>
                    <td>Delegated to downstream consumer tools (FSR/NIROS, ECAC contour engine)</td>
                    <td><span class="badge badge-secondary">SCOPE COMPLIANT</span></td>
                </tr>
                <tr>
                    <td><strong>Verification Framework</strong></td>
                    <td>Vol 3 reference cases: 12 noise cases &amp; 26 performance cases</td>
                    <td>Leave-one-aircraft-out cross-validation harness (<code>loo_validate</code>)</td>
                    <td><span class="badge badge-danger">HIGH-VALUE GAP</span></td>
                </tr>
            </tbody>
        </table>
    </div>
    """

    doc29_struct_html = """
    <div class="diagram-box page-break-inside-avoid">
        <div class="diagram-title">ECAC CEAC DOC 29 5th EDITION STRUCTURE</div>
        <div class="volume-grid">
            <div class="volume-card">
                <div class="volume-header">VOLUME 1</div>
                <div class="volume-sub">Applications Guide</div>
                <ul class="volume-list">
                    <li>Noise Contours &amp; Policy</li>
                    <li>Cumulative Metrics ($L_{\\text{den}}$, $L_{\\text{night}}$)</li>
                    <li>ANP Data Operational Rules</li>
                    <li>Proxy Substitutions</li>
                </ul>
            </div>
            <div class="volume-card volume-card-accent">
                <div class="volume-header">VOLUME 2</div>
                <div class="volume-sub">Technical Guide (Mathematics)</div>
                <ul class="volume-list">
                    <li>Segment Noise Equations</li>
                    <li>NPD Interpolation &amp; Extrapolation</li>
                    <li>Lateral Attenuation &amp; Ground Effect</li>
                    <li>Trajectory Integration Kinematics</li>
                </ul>
            </div>
            <div class="volume-card">
                <div class="volume-header">VOLUME 3</div>
                <div class="volume-sub">Reference Cases &amp; Verification</div>
                <ul class="volume-list">
                    <li>12 Noise Benchmark Cases</li>
                    <li>26 Performance Trajectory Cases</li>
                    <li>Numerical Standard Benchmarks</li>
                    <li>&plusmn;0.1 dB Verification Suite</li>
                </ul>
            </div>
        </div>
    </div>
    """

    pipeline_html = """
    <div class="diagram-box page-break-inside-avoid">
        <div class="diagram-title">VOLUME 2 NOISE CALCULATION PIPELINE</div>
        <div class="pipeline-flow">
            <div class="pipeline-step">
                <div class="step-title">Segment State</div>
                <div class="step-desc">
                    &bull; Corrected Thrust $P$<br>
                    &bull; Slant Distance $d$<br>
                    &bull; Ground Speed $V$
                </div>
            </div>
            <div class="pipeline-arrow">&rarr;</div>
            <div class="pipeline-step">
                <div class="step-title">Base NPD Lookup</div>
                <div class="step-desc">
                    $L_{\\text{NPD}}(P, d)$<br>
                    $\\log_{10}(d)$ Interpolation
                </div>
            </div>
            <div class="pipeline-arrow">&rarr;</div>
            <div class="pipeline-step step-wide">
                <div class="step-title">Segment Corrections</div>
                <div class="step-desc">
                    &bull; Duration: $\\Delta_V = 10 \\log_{10}(V_{\\text{ref}}/V)$<br>
                    &bull; Installation: $\\Delta_I(\\phi)$<br>
                    &bull; Lateral Atten: $\\Lambda(\\beta, \\ell)$<br>
                    &bull; Finite Segment: $\\Delta_F$<br>
                    &bull; Start-of-Roll: $\\Delta_{\\text{SOR}}$
                </div>
            </div>
            <div class="pipeline-arrow">&rarr;</div>
            <div class="pipeline-step step-output">
                <div class="step-title">Ground Level $L_{\\text{seg}}$</div>
                <div class="step-desc">
                    &bull; $L_{\\text{maxseg}}$ ($L_{\\text{Amax}}$)<br>
                    &bull; $L_{\\text{Sseg}}$ ($SEL$)
                </div>
            </div>
        </div>
    </div>
    """

    literature_html = """
    <div class="diagram-box page-break-inside-avoid">
        <div class="diagram-title">ACADEMIC &amp; INDUSTRIAL LITERATURE CORPUS</div>
        <div class="volume-grid">
            <div class="volume-card">
                <div class="volume-header">REGIONAL / OPEN TOOLS</div>
                <ul class="volume-list">
                    <li><strong>Soto-Molina (2025):</strong> Spanish Open-Source Doc 29 Tool</li>
                    <li><strong>Feng et al. (2023):</strong> Aviation Noise Model Taxonomy</li>
                    <li><strong>Jandl (2011):</strong> Flight Sim &amp; Doc 29 Integration</li>
                    <li><strong>Georgieva (2020):</strong> 4-DOF MATLAB Takeoff Physics</li>
                </ul>
            </div>
            <div class="volume-card volume-card-accent">
                <div class="volume-header">COMPONENT PHYSICS &amp; ANOPP</div>
                <ul class="volume-list">
                    <li><strong>NASA ANOPP:</strong> Jet, Fan, Core &amp; Airframe Semi-Empirics</li>
                    <li><strong>Thoma et al. (2023):</strong> A321neo pyNA/ANOPP Validation</li>
                    <li><strong>Fink / Stone / Heidmann:</strong> Noise Component Scaling</li>
                    <li><strong>Ayton et al. (2020):</strong> Porous Airfoil Turbulence</li>
                </ul>
            </div>
            <div class="volume-card">
                <div class="volume-header">EMPIRICAL / FLIGHT DATA</div>
                <ul class="volume-list">
                    <li><strong>Schwab &amp; Zellmann (2020):</strong> sonAIR FDR/ADS-B Estimator</li>
                    <li><strong>Zellmann et al. (2018):</strong> sonAIR 19-Aircraft Directivity</li>
                    <li><strong>Muller (1971):</strong> Sound Energy Duration Math</li>
                    <li><strong>EASA ANP Table:</strong> Verified Proxy Substitutions</li>
                </ul>
            </div>
        </div>
    </div>
    """

    architecture_html = """
    <div class="diagram-box page-break-inside-avoid">
        <div class="diagram-title">PNMF SYSTEM ARCHITECTURE (projects/pnmf)</div>
        <div class="arch-container">
            <div class="arch-box arch-input">
                <div class="arch-title">Parametric Concept Input</div>
                <div class="arch-desc">
                    &bull; MTOW, MLW<br>
                    &bull; Static Thrust, BPR<br>
                    &bull; $N_{\\text{engines}}$, Engine Type<br>
                    &bull; Noise Chapter
                </div>
            </div>
            <div class="arch-routes">
                <div class="arch-box arch-route">
                    <div class="arch-title">Route 1: Data-Driven Surrogate</div>
                    <div class="arch-desc">Multi-Output Extra Trees / Random Forest trained on 122 ANP sets</div>
                </div>
                <div class="arch-divider">&bull; QA GATE CHECKS DISAGREEMENT (&gt; 5.0 dB) &bull;</div>
                <div class="arch-box arch-route">
                    <div class="arch-title">Route 2: Component Physics Model</div>
                    <div class="arch-desc">1/3-Octave (50 Hz - 10 kHz) Stone / Heidmann / Fink (Frozen A320 Fit)</div>
                </div>
            </div>
            <div class="arch-box arch-output">
                <div class="arch-title">ANP / ECAC Ecosystem</div>
                <div class="arch-desc">
                    &bull; EASA ANP SQLite DB<br>
                    &bull; Standard NPD Grid CSV<br>
                    &bull; FSR / NIROS Contours
                </div>
            </div>
        </div>
    </div>
    """

    eval_matrix_html = """
    <div class="card-container page-break-inside-avoid">
        <div class="card-header">
            <h3><span class="badge badge-primary">EXHAUSTIVE</span> Technical Evaluation Matrix</h3>
        </div>
        <table class="styled-table">
            <thead>
                <tr>
                    <th style="width: 15%;">Feature</th>
                    <th style="width: 22%;">ECAC Doc 29 5th Ed. Standard</th>
                    <th style="width: 22%;">SOTA Literature Standard</th>
                    <th style="width: 23%;">PNMF Implementation</th>
                    <th style="width: 18%;">Verdict</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>NPD Grid</strong></td>
                    <td>10 standard distances (200-25k ft)</td>
                    <td>Standard ANP slant distances</td>
                    <td><code>STANDARD_DISTANCES_FT</code> in <code>core.py</code></td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Metrics</strong></td>
                    <td>SEL, LAmax, EPNL, PNLTM</td>
                    <td>Full metric coverage</td>
                    <td>Surrogate: 4 metrics; Physics: SEL &amp; LAmax</td>
                    <td><span class="badge badge-warning">PARTIAL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Interpolation</strong></td>
                    <td>Linear in $\\log_{10}(d)$</td>
                    <td>Linear in $\\log_{10}(d)$</td>
                    <td><code>NPDTable.level()</code> low/high end-slopes</td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Monotonicity</strong></td>
                    <td>Sound non-increases with distance</td>
                    <td>Monotonic distance decay</td>
                    <td>Enforced via <code>IsotonicRegression</code></td>
                    <td><span class="badge badge-star">SUPERIOR / EXCEEDS</span></td>
                </tr>
                <tr>
                    <td><strong>Power Units</strong></td>
                    <td>Mixes lb, % static thrust, RPM</td>
                    <td>Standardized thrust decks</td>
                    <td><code>power_features()</code> maps to $P_{\\text{lb}}$ &amp; throttle %</td>
                    <td><span class="badge badge-star">SUPERIOR / EXCEEDS</span></td>
                </tr>
                <tr>
                    <td><strong>Atmosphere</strong></td>
                    <td>ISO 9613-1 / ARP 866A ISA</td>
                    <td>ISO 9613-1 frequency absorption</td>
                    <td><code>physics.py</code> exact relaxation equations</td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Trajectory</strong></td>
                    <td>App B procedural steps</td>
                    <td>FDR/ADS-B kinematic profiles</td>
                    <td><code>DepartureSynthesizer</code> for 142 aircraft</td>
                    <td><span class="badge badge-info">SUBSTANTIALLY COMPLIANT</span></td>
                </tr>
                <tr>
                    <td><strong>Segment Dist.</strong></td>
                    <td>Perpendicular / closest approach</td>
                    <td>Analytic minimum slant distance</td>
                    <td><code>operations.py::flyover_level()</code> analytic point-to-segment</td>
                    <td><span class="badge badge-success">FULL COMPLIANCE</span></td>
                </tr>
                <tr>
                    <td><strong>Physics Scope</strong></td>
                    <td>1/3-octave spectral synthesis</td>
                    <td>NASA ANOPP models</td>
                    <td>Stone (jet), Heidmann (fan), Fink (airframe)</td>
                    <td><span class="badge badge-info">FULL ANOPP ALIGNMENT</span></td>
                </tr>
                <tr>
                    <td><strong>Truth Separ.</strong></td>
                    <td>Data integrity invariant</td>
                    <td>Zero training set leakage</td>
                    <td>SQLite <code>anp_*</code> vs <code>predicted_*</code> invariant</td>
                    <td><span class="badge badge-star">STRICT ARCHITECTURAL</span></td>
                </tr>
                <tr>
                    <td><strong>Propagation</strong></td>
                    <td>Lateral attenuation &amp; shielding</td>
                    <td>Air-to-ground attenuation</td>
                    <td>Delegated to downstream contour tools</td>
                    <td><span class="badge badge-secondary">SCOPE COMPLIANT</span></td>
                </tr>
                <tr>
                    <td><strong>Verification</strong></td>
                    <td>Vol 3: 12 noise &amp; 26 perf cases</td>
                    <td>Benchmarked test suite</td>
                    <td>Leave-one-out cross-validation harness</td>
                    <td><span class="badge badge-danger">HIGH-VALUE GAP</span></td>
                </tr>
            </tbody>
        </table>
    </div>
    """

    roadmap_html = """
    <div class="diagram-box page-break-inside-avoid">
        <div class="diagram-title">PNMF FUTURE DEVELOPMENT ROADMAP</div>
        <div class="volume-grid">
            <div class="volume-card volume-card-danger">
                <div class="volume-header">HIGHEST PRIORITY (Immediate)</div>
                <ul class="volume-list">
                    <li><strong>Doc 29 Vol 3 Verification:</strong> Automated pytest suite for 12 noise &amp; 26 perf cases (&plusmn;0.1 dB accuracy)</li>
                    <li><strong>Parametric Synthesis Link:</strong> Consume geometric params directly from CPACS / RCAIDE</li>
                </ul>
            </div>
            <div class="volume-card volume-card-accent">
                <div class="volume-header">HIGH PRIORITY (Near-Term)</div>
                <ul class="volume-list">
                    <li><strong>Physics EPNL/PNLTM Tones:</strong> Implement &Delta;C tone penalty &amp; duration integration in physics route</li>
                    <li><strong>OOD Detector:</strong> Mahalanobis distance filter for exotic aircraft concepts</li>
                </ul>
            </div>
            <div class="volume-card">
                <div class="volume-header">MEDIUM PRIORITY (Long-Term)</div>
                <ul class="volume-list">
                    <li><strong>Conformal Prediction:</strong> Calibrated 95% confidence bounds for surrogate predictions</li>
                    <li><strong>Advanced Shielding:</strong> UHBR &amp; distributed electric propulsion directivity models</li>
                </ul>
            </div>
        </div>
    </div>
    """

    # Use lambdas for re.sub to prevent backslash interpretation errors
    md_content = re.sub(
        r'```\r?\n===+\r?\n\s*PNMF EVALUATION AT A GLANCE\s*\r?\n===+[\s\S]*?```',
        lambda m: at_a_glance_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n\s*┌─+┐\r?\n\s*│\s*ECAC CEAC DOC 29 5th EDITION\s*│[\s\S]*?```',
        lambda m: doc29_struct_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n\s*VOLUME 2 NOISE CALCULATION PIPELINE[\s\S]*?```',
        lambda m: pipeline_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n\s*┌─+┐\r?\n\s*│\s*ACADEMIC & INDUSTRIAL LITERATURE CORPUS\s*│[\s\S]*?```',
        lambda m: literature_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n\s*PNMF SYSTEM ARCHITECTURE[\s\S]*?```',
        lambda m: architecture_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n===+\r?\n\s*EXHAUSTIVE TECHNICAL EVALUATION MATRIX\s*\r?\n===+[\s\S]*?```',
        lambda m: eval_matrix_html,
        md_content
    )

    md_content = re.sub(
        r'```\r?\n\s*┌─+┐\r?\n\s*│\s*PNMF FUTURE DEVELOPMENT ROADMAP\s*│[\s\S]*?```',
        lambda m: roadmap_html,
        md_content
    )

    lines = md_content.split('\n')
    html_lines = []
    in_list = False
    skip_first_h1 = True

    for line in lines:
        stripped = line.strip()
        
        if stripped.startswith('<div class="math-display">'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(line)
            continue

        if stripped.startswith('# '):
            if in_list: html_lines.append('</ul>'); in_list = False
            if skip_first_h1:
                skip_first_h1 = False
                continue
            html_lines.append(f'<h1 class="report-h1">{stripped[2:]}</h1>')
        elif stripped.startswith('## '):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h2 class="report-h2">{stripped[3:]}</h2>')
        elif stripped.startswith('### '):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h3 class="report-h3">{stripped[4:]}</h3>')
        elif stripped.startswith('#### '):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append(f'<h4 class="report-h4">{stripped[5:]}</h4>')
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_list:
                html_lines.append('<ul class="report-ul">')
                in_list = True
            item_text = stripped[2:]
            item_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', item_text)
            item_text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', item_text)
            html_lines.append(f'<li>{item_text}</li>')
        elif re.match(r'^\d+\.\s', stripped):
            if in_list: html_lines.append('</ul>'); in_list = False
            item_text = re.sub(r'^\d+\.\s', '', stripped)
            item_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', item_text)
            item_text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', item_text)
            html_lines.append(f'<p class="numbered-item"><strong>{stripped.split(".")[0]}.</strong> {item_text}</p>')
        elif stripped.startswith('---'):
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append('<hr class="report-hr">')
        elif stripped == '':
            if in_list: html_lines.append('</ul>'); in_list = False
            html_lines.append('<div class="spacer"></div>')
        else:
            if in_list: html_lines.append('</ul>'); in_list = False
            if stripped.startswith('<div') or stripped.startswith('<table') or stripped.startswith('</') or stripped.startswith('<a'):
                html_lines.append(line)
            else:
                formatted_line = line
                formatted_line = re.sub(r'`([^`]+)`', r'<code>\1</code>', formatted_line)
                formatted_line = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', formatted_line)
                html_lines.append(f'<p class="report-p">{formatted_line}</p>')

    if in_list:
        html_lines.append('</ul>')

    return '\n'.join(html_lines)

def convert_md_file_to_pdf(md_path, pdf_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    body_html = parse_markdown_to_html(md_content)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>ECAC Doc 29 5th Edition Master Technical Report</title>
    <!-- KaTeX CSS & JS -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js" onload="renderMathInElement(document.body, {{ delimiters: [ {{left: '$$', right: '$$', display: true}}, {{left: '$', right: '$', display: false}} ] }});"></script>
    <style>
        @page {{
            size: A4 portrait;
            margin: 20mm 15mm 20mm 15mm;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: #1e293b;
            line-height: 1.55;
            font-size: 10pt;
            background-color: #ffffff;
            margin: 0;
            padding: 0;
        }}

        /* Header Banner */
        .report-header-banner {{
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #334155 100%);
            color: #ffffff;
            padding: 24px 28px;
            border-radius: 8px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
        }}

        .report-header-banner h1 {{
            font-size: 18pt;
            font-weight: 700;
            margin: 0 0 14px 0;
            line-height: 1.3;
            letter-spacing: -0.02em;
            color: #ffffff;
            border-bottom: 2px solid #38bdf8;
            padding-bottom: 10px;
        }}

        .metadata-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px 20px;
            font-size: 9pt;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
        }}

        .meta-label {{
            font-weight: 600;
            color: #94a3b8;
            width: 130px;
            text-transform: uppercase;
            font-size: 7.5pt;
            letter-spacing: 0.05em;
        }}

        .meta-value {{
            color: #f8fafc;
            font-weight: 500;
        }}

        /* Typography */
        .report-h1 {{
            font-size: 15pt;
            font-weight: 700;
            color: #0f172a;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 6px;
            margin-top: 28px;
            margin-bottom: 12px;
            page-break-after: avoid;
        }}

        .report-h2 {{
            font-size: 12.5pt;
            font-weight: 600;
            color: #1e3a8a;
            margin-top: 22px;
            margin-bottom: 10px;
            border-left: 4px solid #2563eb;
            padding-left: 10px;
            page-break-after: avoid;
        }}

        .report-h3 {{
            font-size: 11pt;
            font-weight: 600;
            color: #0f172a;
            margin-top: 16px;
            margin-bottom: 8px;
            page-break-after: avoid;
        }}

        .report-h4 {{
            font-size: 10pt;
            font-weight: 600;
            color: #334155;
            margin-top: 12px;
            margin-bottom: 6px;
            page-break-after: avoid;
        }}

        .report-p {{
            margin-top: 0;
            margin-bottom: 10px;
            text-align: justify;
        }}

        .numbered-item {{
            margin-top: 4px;
            margin-bottom: 6px;
        }}

        code {{
            font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
            background-color: #f1f5f9;
            color: #0f172a;
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 8.5pt;
            border: 1px solid #e2e8f0;
        }}

        .report-link {{
            color: #2563eb;
            text-decoration: none;
            word-break: break-all;
        }}

        .report-link:hover {{
            text-decoration: underline;
        }}

        .report-ul {{
            margin-top: 4px;
            margin-bottom: 10px;
            padding-left: 20px;
        }}

        .report-ul li {{
            margin-bottom: 4px;
        }}

        .report-hr {{
            border: 0;
            height: 1px;
            background: #cbd5e1;
            margin: 20px 0;
        }}

        .spacer {{
            height: 6px;
        }}

        .page-break-inside-avoid {{
            page-break-inside: avoid;
        }}

        /* Badges */
        .badge {{
            display: inline-block;
            padding: 3px 7px;
            font-size: 7.5pt;
            font-weight: 700;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}

        .badge-primary {{ background-color: #3b82f6; color: #ffffff; }}
        .badge-success {{ background-color: #10b981; color: #ffffff; }}
        .badge-star {{ background-color: #1e1b4b; color: #818cf8; border: 1px solid #6366f1; }}
        .badge-info {{ background-color: #6366f1; color: #ffffff; }}
        .badge-warning {{ background-color: #f59e0b; color: #ffffff; }}
        .badge-secondary {{ background-color: #64748b; color: #ffffff; }}
        .badge-danger {{ background-color: #ef4444; color: #ffffff; }}

        /* Cards & Tables */
        .card-container {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            margin: 16px 0;
            overflow: hidden;
            box-shadow: 0 2px 6px rgba(0,0,0,0.04);
        }}

        .card-header {{
            background: #f8fafc;
            border-bottom: 1px solid #cbd5e1;
            padding: 10px 16px;
        }}

        .card-header h3 {{
            margin: 0;
            font-size: 10.5pt;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .styled-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 8.5pt;
        }}

        .styled-table th {{
            background-color: #1e293b;
            color: #ffffff;
            text-align: left;
            padding: 8px 10px;
            font-weight: 600;
        }}

        .styled-table td {{
            padding: 8px 10px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: top;
        }}

        .styled-table tbody tr:nth-of-type(even) {{
            background-color: #f8fafc;
        }}

        /* Diagrams */
        .diagram-box {{
            background: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 8px;
            padding: 14px;
            margin: 18px 0;
        }}

        .diagram-title {{
            font-size: 9.5pt;
            font-weight: 700;
            color: #1e293b;
            text-align: center;
            margin-bottom: 12px;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }}

        .volume-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }}

        .volume-card {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 10px;
        }}

        .volume-card-accent {{
            border-top: 3px solid #2563eb;
            background: #f0f9ff;
        }}

        .volume-card-danger {{
            border-top: 3px solid #dc2626;
            background: #fef2f2;
        }}

        .volume-header {{
            font-size: 9pt;
            font-weight: 700;
            color: #0f172a;
        }}

        .volume-sub {{
            font-size: 7.5pt;
            color: #64748b;
            margin-bottom: 8px;
            font-style: italic;
        }}

        .volume-list {{
            margin: 0;
            padding-left: 14px;
            font-size: 8pt;
            color: #334155;
        }}

        .volume-list li {{
            margin-bottom: 4px;
        }}

        /* Pipeline Flowchart */
        .pipeline-flow {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 6px;
        }}

        .pipeline-step {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 8px;
            flex: 1;
            font-size: 7.5pt;
        }}

        .step-wide {{ flex: 1.4; }}
        .step-output {{ border-left: 3px solid #10b981; background: #ecfdf5; }}

        .step-title {{
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 4px;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 2px;
        }}

        .pipeline-arrow {{
            font-weight: bold;
            color: #64748b;
            font-size: 12pt;
        }}

        /* Architecture Diagram */
        .arch-container {{
            display: flex;
            align-items: stretch;
            gap: 12px;
        }}

        .arch-box {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 10px;
            font-size: 8pt;
        }}

        .arch-input {{ flex: 1; border-left: 3px solid #3b82f6; }}
        .arch-routes {{ flex: 2; display: flex; flex-direction: column; gap: 6px; }}
        .arch-route {{ background: #f1f5f9; }}
        .arch-divider {{ font-size: 7pt; color: #475569; font-weight: bold; text-align: center; margin: 2px 0; }}
        .arch-output {{ flex: 1; border-left: 3px solid #10b981; background: #f0fdf4; }}

        .arch-title {{
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 4px;
        }}

        /* Math Styling */
        .math-display {{
            text-align: center;
            margin: 12px 0;
            padding: 8px 12px;
            background-color: #f8fafc;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
            font-size: 10pt;
            overflow-x: auto;
        }}

        .katex-display {{
            margin: 0 !important;
        }}
    </style>
</head>
<body>

<div class="report-header-banner">
    <h1>Comprehensive Master Technical Report: ECAC Doc 29 5th Edition Standards Analysis, Literature Synthesis &amp; PNMF System Evaluation</h1>
    <div class="metadata-grid">
        <div class="meta-item">
            <span class="meta-label">Document Status</span>
            <span class="meta-value">Comprehensive Master Evaluation Report</span>
        </div>
        <div class="meta-item">
            <span class="meta-label">Target Project</span>
            <span class="meta-value"><code>projects/pnmf</code> (Parametric Noise Modeling Framework)</span>
        </div>
        <div class="meta-item">
            <span class="meta-label">Governance Root</span>
            <span class="meta-value">EFES / TU Darmstadt FSR (Prof. Klingauf, sup. L. Kempf)</span>
        </div>
        <div class="meta-item">
            <span class="meta-label">Report Date</span>
            <span class="meta-value">July 31, 2026</span>
        </div>
    </div>
</div>

{body_html}

</body>
</html>
"""

    output_html_path = md_path.replace('.md', '_generated.html')
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(full_html)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        file_url = f"file:///{os.path.abspath(output_html_path).replace('\\', '/')}"
        page.goto(file_url, wait_until='networkidle')
        page.wait_for_selector('.katex', timeout=10000)
        
        page.pdf(
            path=pdf_path,
            format='A4',
            print_background=True,
            display_header_footer=True,
            header_template='<div style="font-size: 7.5pt; font-family: sans-serif; color: #94a3b8; width: 100%; text-align: right; padding-right: 15mm;">ECAC Doc 29 5th Edition Evaluation Report | projects/pnmf</div>',
            footer_template='<div style="font-size: 7.5pt; font-family: sans-serif; color: #94a3b8; width: 100%; display: flex; justify-content: space-between; padding: 0 15mm;"><span class="title">PNMF Master Report | ECAC Doc 29 5th Edition Evaluation</span><span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span></div>',
            margin={
                'top': '18mm',
                'bottom': '18mm',
                'left': '15mm',
                'right': '15mm'
            }
        )
        browser.close()
    print(f"PDF successfully compiled to: {pdf_path}")

if __name__ == '__main__':
    md_file = r"c:\Users\efeko\adp\framework\pnmf_project_2\pnmf_project\projects\pnmf\docs\ECAC_5TH_EDITION_ANALYSIS_AND_EVALUATION_REPORT.md"
    pdf_file = r"c:\Users\efeko\adp\framework\pnmf_project_2\pnmf_project\projects\pnmf\docs\ECAC_5TH_EDITION_ANALYSIS_AND_EVALUATION_REPORT.pdf"
    
    convert_md_file_to_pdf(md_file, pdf_file)
