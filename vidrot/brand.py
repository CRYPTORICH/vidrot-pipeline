"""FFmpeg branding. Normalizes every clip to 1080x1920, then stitches.

The desktop pipeline concatenated mismatched files and the join often failed.
Re-encoding first is what makes the reel reliable. A missing Blender bumper
is replaced with a two-second title card.
"""
import shutil
import subprocess
from pathlib import Path


def ffmpeg_bin(explicit=""):
    if explicit:
        return explicit if shutil.which(explicit) or Path(explicit).exists() else ""
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or ""


def find_font():
    candidates = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def ffmpeg_font(path):
    text = Path(path).as_posix()
    if len(text) > 1 and text[1] == ":":
        text = text[0] + r"\:" + text[2:]
    return text.replace("'", "")


def ffmpeg_text(text):
    cleaned = str(text or "").replace("\\", " ").replace(":", " ").replace("'", "")
    return " ".join(cleaned.split())[:80] or "VIDROT"


def run_ffmpeg(cmd, timeout=180):
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg is not installed or not on PATH."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg took too long and was stopped."}
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        tail = err.strip().splitlines()[-1] if err.strip() else "ffmpeg failed"
        return {"ok": False, "error": tail[:300]}
    return {"ok": True, "error": ""}


def _drawtext(text, font, size, y_expr):
    label = ffmpeg_text(text)
    font_bit = f"fontfile='{ffmpeg_font(font)}':" if font else ""
    return (
        f"drawtext={font_bit}text='{label}':fontsize={size}:fontcolor=white:"
        f"borderw=2:bordercolor=black:x=(w-text_w)/2:y={y_expr}"
    )


def normalize_command(ffmpeg, src, dest, label, font):
    video = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,format=yuv420p"
    if label:
        video += "," + _drawtext(label, font, 42, "h-th-80")
        video += "," + _drawtext("VIDROT", font, 28, "80")
    return [
        ffmpeg, "-y", "-i", str(src),
        "-vf", video,
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(dest),
    ]


def title_card_command(ffmpeg, dest, line, font, seconds=2):
    draw = _drawtext(line, font, 42, "(h-text_h)/2")
    brand = _drawtext("VIDROT", font, 28, "80")
    return [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", f"color=c=0x141810:s=1080x1920:d={int(seconds)}",
        "-vf", f"{draw},{brand},format=yuv420p",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        str(dest),
    ]


def poster_command(ffmpeg, src, dest):
    return [ffmpeg, "-y", "-ss", "0.4", "-i", str(src), "-frames:v", "1", str(dest)]


def concat_command(ffmpeg, list_file, dest):
    return [
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(dest),
    ]


def _must_exist(result, dest):
    if result["ok"] and not Path(dest).exists():
        return {"ok": False, "error": "ffmpeg did not write the output file."}
    if result["ok"]:
        result["path"] = str(dest)
    return result


def write_title_card(dest, line, ffmpeg=""):
    binary = ffmpeg_bin(ffmpeg)
    if not binary:
        return {"ok": False, "error": "ffmpeg is not installed, so a preview card could not be made."}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = title_card_command(binary, dest, line, find_font())
    return _must_exist(run_ffmpeg(cmd, timeout=60), dest)


def normalize_clip(src, dest, label, ffmpeg=""):
    binary = ffmpeg_bin(ffmpeg)
    if not binary:
        return {"ok": False, "error": "ffmpeg is not installed."}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = normalize_command(binary, src, dest, label, find_font())
    return _must_exist(run_ffmpeg(cmd), dest)


def write_poster(src, dest, ffmpeg=""):
    binary = ffmpeg_bin(ffmpeg)
    if not binary:
        return {"ok": False, "error": "ffmpeg is not installed."}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return _must_exist(run_ffmpeg(poster_command(binary, src, dest), timeout=30), dest)


def stitch(clips, dest, bumper=None, ffmpeg=""):
    """clips is a list of existing normalized mp4 paths, in order."""
    binary = ffmpeg_bin(ffmpeg)
    if not binary:
        return {"ok": False, "error": "ffmpeg is not installed."}
    files = [Path(p) for p in clips if p and Path(p).exists()]
    if bumper and Path(bumper).exists():
        files.insert(0, Path(bumper))
    if not files:
        return {"ok": False, "error": "No clips were ready to stitch."}
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    list_file = dest.with_suffix(".txt")
    lines = []
    for path in files:
        escaped = path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = _must_exist(run_ffmpeg(concat_command(binary, list_file, dest)), dest)
    return result
