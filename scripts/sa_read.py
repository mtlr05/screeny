#!/usr/bin/env python3
"""Read one Seeking Alpha queue in an ordinary Google Chrome window.

Chrome is started as a normal process, not by Playwright. Playwright's
debugger and --no-sandbox flag make a human Press & Hold fail. This script
does not press the button, and it does not read or store a login or a cookie.

  python scripts/sa_read.py reports/sa_read_order_<date>.csv
  python scripts/sa_read.py --self-test

The Chrome profile lives outside the repo, at ~/.screeny/chrome_sa. Sign in
once in that window if the account menu is missing.
"""
import argparse
import base64
import datetime as dt
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sa_ingest
from _paths import FULLTEXT, REPORTS, STATE

GAP_SECONDS = 25
POLL_SECONDS = 3
LOAD_SECONDS = 20
PROFILE = os.path.join(os.path.expanduser("~"), ".screeny", "chrome_sa")
DENIED = re.compile(r"access to this page has been denied", re.I)
SUMMARY = re.compile(r"(?:^|\n)Summary\n", re.I)
DISCLOSURE = re.compile(r"Analyst['\u2019]s Disclosure:", re.I)
SIGNED_OUT = re.compile(r"create free account", re.I)
SIGNED_IN = re.compile(r"\bSign out\b", re.I)


def is_hold(title, text):
    """A Press & Hold page or an access-denied title. An article body is not."""
    blob = "%s\n%s" % (title or "", text or "")
    if DENIED.search(title or ""):
        return True
    if sa_ingest.BOT.search(blob) and not DISCLOSURE.search(text or ""):
        return True
    return False


def is_signed_out(text):
    return bool(SIGNED_OUT.search(text or "")) and not SIGNED_IN.search(text or "")


def is_article(text):
    return bool(SUMMARY.search(text or "") and DISCLOSURE.search(text or ""))


def page_kind(title, text):
    if is_hold(title, text):
        return "hold"
    if is_article(text):
        return "article"
    if is_signed_out(text):
        return "signin"
    return "loading"


def split_article(text):
    """Summary, body, and analyst disclosure from rendered page text."""
    raw = text or ""
    summary_at = SUMMARY.search(raw)
    disclosure_at = DISCLOSURE.search(raw)
    if not summary_at or not disclosure_at or disclosure_at.start() <= summary_at.end():
        return "", raw.strip(), ""
    middle = raw[summary_at.end():disclosure_at.start()].strip()
    disclosure = raw[disclosure_at.start():]
    disclosure = re.split(r"\nSeeking Alpha['\u2019]s Disclosure:", disclosure, maxsplit=1)[0].strip()
    lines = [line.strip() for line in middle.splitlines() if line.strip()]
    summary_lines = []
    body_lines = []
    for line in lines:
        if not body_lines and len(line) < 280 and not line.endswith("."):
            summary_lines.append(line)
            continue
        if not body_lines and len(summary_lines) < 6 and len(line) < 220:
            summary_lines.append(line)
            continue
        body_lines.append(line)
    if not body_lines:
        body_lines = summary_lines
        summary_lines = []
    return "\n".join(summary_lines), "\n".join(body_lines), disclosure


def body_words(body):
    return len(sa_ingest.unwrap_lines(body or "").split())


def format_fulltext(url, title, author, date, ticker, summary, body, disclosure):
    return "\n".join([
        "URL: %s" % (url or ""),
        "TITLE: %s" % sa_ingest.scrub(title or ""),
        "AUTHOR: %s" % sa_ingest.scrub(author or ""),
        "DATE: %s" % (date or ""),
        "TICKERS: %s" % (ticker or ""),
        "",
        "=== SUMMARY ===",
        summary or "",
        "",
        "=== ARTICLE BODY ===",
        body or "",
        "",
        "=== ANALYST'S DISCLOSURE ===",
        disclosure or "",
        "",
    ])


def candidates_path_for(order_path):
    name = os.path.basename(order_path)
    date = name.replace("sa_read_order_", "").replace(".csv", "")
    return os.path.join(REPORTS, "sa_candidates_%s.csv" % date)


def progress_path_for(order_path):
    name = os.path.basename(order_path)
    date = name.replace("sa_read_order_", "").replace(".csv", "")
    return os.path.join(REPORTS, "sa_read_progress_%s.log" % date)


def log_progress(path, message):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    line = "%s %s\n" % (stamp, message)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
    print(line, end="")


def pending_rows(order_path, results_path):
    """Rows resume still wants, with date and title from the order file."""
    wanted = {item["id"] for item in sa_ingest.resume(order_path, results_path)}
    rows = []
    for row in sa_ingest.read_csv(order_path):
        aid = sa_ingest.article_id(row.get("url") or "") or (row.get("article_id") or "")
        if aid in wanted:
            rows.append(row)
    return rows


def author_for(candidates, aid):
    for row in candidates:
        if sa_ingest.article_id(row.get("url") or "") == aid:
            return row.get("author") or ""
    return ""


class SandboxBar(RuntimeError):
    """The Chrome window was started with a flag that draws the yellow bar."""


def chrome_executable():
    """Real installed Google Chrome, not Playwright's Chromium and not Edge."""
    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    seen = []
    for root in roots:
        path = os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")
        seen.append(path)
        if path and os.path.isfile(path):
            return path
    raise RuntimeError("Google Chrome was not found. Looked at: " + " | ".join(seen))


def chrome_command(url, exe=None):
    """Ordinary Chrome. No sandbox switch, no automation switch, no blink flag."""
    exe = exe or chrome_executable()
    args = [
        exe,
        "--user-data-dir=%s" % PROFILE,
        "--force-renderer-accessibility",
        url,
    ]
    for arg in args:
        if arg == "--no-sandbox" or arg.startswith("--enable-automation") or arg.startswith("--disable-blink-features"):
            raise RuntimeError("refusing automation flag %s" % arg)
    return args


def _powershell(script, timeout=25):
    """Run a script. -Command - does not read stdin, so the script is encoded."""
    wrapped = "$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8\r\n" + script
    encoded = base64.b64encode(wrapped.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return completed.stdout or ""


def profile_chrome_command():
    """Command line of the Chrome window that owns this profile. Empty if none."""
    script = r"""
$ProgressPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine -like '*chrome_sa*' -and $_.CommandLine -notlike '*--type=*'
} | Select-Object -ExpandProperty CommandLine
"""
    return _powershell(script).strip()


def stop_profile_chrome():
    """Close only the Chrome that is using the screeny profile."""
    script = r"""
$ProgressPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine -like '*chrome_sa*'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
"""
    _powershell(script)
    for _ in range(20):
        if not profile_chrome_command():
            return
        time.sleep(0.25)


def _clear_restored_tabs():
    """Drop restored tabs so the next launch is the one requested URL."""
    default = os.path.join(PROFILE, "Default")
    if not os.path.isdir(default):
        return
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        path = os.path.join(default, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
    sessions = os.path.join(default, "Sessions")
    if os.path.isdir(sessions):
        for name in os.listdir(sessions):
            try:
                os.remove(os.path.join(sessions, name))
            except OSError:
                pass


def launch_chrome(url):
    """Start one ordinary Chrome window on this URL. Returns the argv used."""
    os.makedirs(PROFILE, exist_ok=True)
    stop_profile_chrome()
    _clear_restored_tabs()
    cmd = chrome_command(url)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 40
    live = ""
    while time.time() < deadline:
        live = profile_chrome_command()
        if live:
            break
        time.sleep(0.4)
    if not live:
        raise RuntimeError("Chrome did not stay open for %s" % url)
    if "--no-sandbox" in live or "--enable-automation" in live or "--disable-blink-features" in live:
        stop_profile_chrome()
        raise SandboxBar(live)
    return cmd


def _snapshot():
    """Title and document text of the profile Chrome window. No debugger attached."""
    script = r"""
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$procs = @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine -like '*chrome_sa*' -and $_.CommandLine -notlike '*--type=*'
})
if ($procs.Count -eq 0) { Write-Output 'NOWINDOW'; exit 0 }
$procId = [int]$procs[0].ProcessId
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $procId)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { Write-Output 'NOWINDOW'; exit 0 }
$title = $win.Current.Name
$docCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
$docs = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, $docCond)
$best = ''
foreach ($doc in $docs) {
  try {
    $pat = $doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
    $text = $pat.DocumentRange.GetText(200000)
    if ($text -and $text.Length -gt $best.Length) { $best = $text }
  } catch {}
}
Write-Output ('TITLE:' + $title)
Write-Output 'BODY-START'
Write-Output $best
Write-Output 'BODY-END'
"""
    try:
        raw = _powershell(script, timeout=45)
    except subprocess.TimeoutExpired:
        return "", ""
    if "NOWINDOW" in raw and "BODY-START" not in raw:
        return None, None
    title = ""
    body = []
    copying = False
    for line in raw.splitlines():
        if line.startswith("TITLE:"):
            title = line[6:].strip()
        elif line.strip() == "BODY-START":
            copying = True
        elif line.strip() == "BODY-END":
            copying = False
        elif copying:
            body.append(line)
    title = re.sub(r"\s+-\s+Google Chrome\s*$", "", title).strip()
    return title, "\n".join(body).strip()


def page_status(title, text):
    """Short title and body note so a hold can be checked from the log."""
    blob = "%s\n%s" % (title or "", text or "")
    low = blob.lower()
    flags = []
    if "unsupported command-line flag" in low or "--no-sandbox" in blob:
        flags.append("infobar-text")
    if "please try again" in low:
        flags.append("please-try-again")
    excerpt = " ".join((text or "").split())
    if len(excerpt) > 220:
        excerpt = excerpt[:220] + "..."
    return "title=%s flags=%s body=%s" % (title or "", ",".join(flags) or "none", excerpt)


def _bar_in(title, text):
    blob = "%s\n%s" % (title or "", text or "")
    low = blob.lower()
    return "unsupported command-line flag" in low or "--no-sandbox" in blob


def scroll_article():
    """Scroll the open article to the disclosure. Does not touch Press & Hold."""
    script = r"""
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$procs = @(Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" | Where-Object {
  $_.CommandLine -and $_.CommandLine -like '*chrome_sa*' -and $_.CommandLine -notlike '*--type=*'
})
if ($procs.Count -eq 0) { exit 0 }
$procId = [int]$procs[0].ProcessId
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $procId)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
if (-not $win) { exit 0 }
$docCond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document)
$doc = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $docCond)
if (-not $doc) { exit 0 }
$node = $doc
$scroll = $null
for ($i = 0; $i -lt 6 -and $node; $i++) {
  try { $scroll = $node.GetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern) } catch { $scroll = $null }
  if ($scroll) { break }
  $node = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($node)
}
if ($scroll) { $scroll.SetScrollPercent(-1, 100) }
"""
    try:
        _powershell(script, timeout=25)
    except subprocess.TimeoutExpired:
        pass


def wait_until_ready(url, label, progress):
    """Wait out a Press & Hold or a sign-in page. Do not navigate away."""
    told_hold = False
    told_signin = False
    started = time.time()
    missed = 0
    scrolled = False
    while True:
        title, text = _snapshot()
        if title is None:
            missed += 1
            if missed >= 2:
                log_progress(progress, "RELAUNCH — the Chrome window closed. Opening it again on the same article.")
                launch_chrome(url)
                missed = 0
                started = time.time()
                scrolled = False
            time.sleep(POLL_SECONDS)
            continue
        missed = 0
        if _bar_in(title, text):
            raise SandboxBar("yellow --no-sandbox bar is on the page")
        kind = page_kind(title, text)
        if kind == "article":
            summary, body, _disclosure = split_article(text)
            words = body_words(body)
            if words >= sa_ingest.MIN_WORDS:
                return title, text
            if not scrolled:
                scroll_article()
                scrolled = True
                time.sleep(2)
                continue
            if time.time() - started < 15:
                time.sleep(POLL_SECONDS)
                continue
            return title, text
        if kind == "hold":
            if not told_hold:
                log_progress(
                    progress,
                    "WAITING %s — Google Chrome window is waiting on %s. Press & Hold is on the page. The yellow --no-sandbox bar is absent. %s"
                    % (label, label, page_status(title, text)),
                )
                told_hold = True
            time.sleep(POLL_SECONDS)
            continue
        if kind == "signin":
            if not told_signin:
                log_progress(progress, "SIGNIN %s — sign in in the Google Chrome window." % label)
                told_signin = True
            time.sleep(POLL_SECONDS)
            continue
        if text and time.time() - started > LOAD_SECONDS and not told_hold and not told_signin:
            return title, text
        time.sleep(1)


def save_article(row, candidates, progress, results_path, candidates_path):
    url = row.get("url") or ""
    aid = sa_ingest.article_id(url) or (row.get("article_id") or "")
    ticker = row.get("ticker") or ""
    label = "%s %s" % (aid, ticker)
    launch_chrome(url)
    title, text = wait_until_ready(url, label, progress)
    summary, body, disclosure = split_article(text)
    if body_words(body) < sa_ingest.MIN_WORDS and page_kind(title, text) == "article":
        log_progress(progress, "RELOAD %s — first save under 600 words" % label)
        launch_chrome(url)
        title, text = wait_until_ready(url, label, progress)
        summary, body, disclosure = split_article(text)
    author = author_for(candidates, aid)
    if not author:
        author = ""
    page_title = title.split("|")[0].strip() if title else ""
    saved = format_fulltext(
        url,
        row.get("title") or page_title,
        author,
        (row.get("date") or "")[:10],
        ticker,
        summary,
        body,
        disclosure,
    )
    os.makedirs(FULLTEXT, exist_ok=True)
    path = os.path.join(FULLTEXT, "sa_%s.txt" % aid)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(saved)
    code = sa_ingest.check(path, results_path, candidates_path)
    log_progress(progress, "SAVED %s words=%s check=%s" % (label, body_words(body), code))
    return code


def read_queue(order_path, results_path, candidates_path, progress):
    rows = pending_rows(order_path, results_path)
    candidates = sa_ingest.read_csv(candidates_path)
    exe = chrome_executable()
    log_progress(progress, "START unread=%s" % len(rows))
    log_progress(
        progress,
        "BROWSER Google Chrome %s — ordinary window, profile outside the repo, no Playwright debugger."
        % exe,
    )
    index = 0
    launch_misses = 0
    while index < len(rows):
        if index:
            time.sleep(GAP_SECONDS)
        row = rows[index]
        try:
            code = save_article(row, candidates, progress, results_path, candidates_path)
        except SandboxBar as exc:
            log_progress(progress, "STOP — yellow --no-sandbox bar. %s" % exc)
            stop_profile_chrome()
            break
        except Exception as exc:
            aid = sa_ingest.article_id(row.get("url") or "")
            log_progress(progress, "ERROR %s %s %s" % (aid, row.get("ticker") or "", exc))
            if "did not stay open" in str(exc):
                launch_misses += 1
                if launch_misses >= 3:
                    log_progress(progress, "STOP — Chrome did not stay open.")
                    break
                continue
            launch_misses = 0
            index += 1
            continue
        launch_misses = 0
        if code == 3:
            log_progress(progress, "SKIP %s — bot-check page was not scored. Continuing." % (row.get("ticker") or ""))
        index += 1
    else:
        stop_profile_chrome()
        log_progress(progress, "DONE")


def self_test():
    hold_title = "Access to this page has been denied"
    hold_text = "Before we continue...\nPress & Hold to confirm you are\na human (and not a bot)."
    assert is_hold(hold_title, hold_text)
    assert page_kind(hold_title, hold_text) == "hold"
    article = (
        "Skip to content\nSummary\n"
        "The shares are a buy because the plant ramps.\n"
        "Margins widen as volume grows.\n\n"
        + ("The company sells parts to utilities and raises prices each year. " * 80)
        + "\nAnalyst's Disclosure: I/we have a beneficial long position in the shares of WIX either through stock ownership.\n"
        "Seeking Alpha's Disclosure: Past performance is no guarantee.\n"
    )
    assert page_kind("Wix Stock | Seeking Alpha", article) == "article"
    assert not is_hold("Wix Stock | Seeking Alpha", article)
    summary, body, disclosure = split_article(article)
    assert "plant ramps" in summary
    assert body_words(body) >= 80
    assert "beneficial long position" in disclosure
    saved = format_fulltext("https://seekingalpha.com/article/1", "Wix", "A", "2026-10-11", "WIX", summary, body, disclosure)
    assert "=== ARTICLE BODY ===" in saved
    assert page_kind("Seeking Alpha", "Create Free Account\nSign in") == "signin"
    assert page_kind("Seeking Alpha", "Create Free Account\nSign out") != "signin"
    cmd = chrome_command("https://seekingalpha.com/article/4953521", exe=r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert cmd[0].lower().endswith("chrome.exe")
    assert any(arg.startswith("--user-data-dir=") for arg in cmd)
    assert "--no-sandbox" not in cmd
    assert "--enable-automation" not in cmd
    assert not any(arg.startswith("--disable-blink-features") for arg in cmd)
    assert cmd[-1].startswith("https://seekingalpha.com/article/4953521")
    print("sa_read self-test ok")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read a Seeking Alpha queue in visible Chrome")
    parser.add_argument("order", nargs="?", default="")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--results", default=os.path.join(STATE, "sa_results.json"))
    parser.add_argument("--candidates", default="")
    args = parser.parse_args(argv)
    if args.self_test or args.order == "self-test":
        return self_test()
    if not args.order:
        parser.error("the read-order CSV is required")
    candidates = args.candidates or candidates_path_for(args.order)
    progress = progress_path_for(args.order)
    read_queue(args.order, args.results, candidates, progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
