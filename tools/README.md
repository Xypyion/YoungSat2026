# Analysis tools

Small Python scripts we wrote while debugging.

| Script | What it does | Needs |
|---|---|---|
| `pyinstaller_extract.py <exe> <outdir>` | Unpacks a PyInstaller `.exe` (reads the `MEI` cookie and the table of contents) | Python 3 |
| `disassemble_py313.py <pyc> <out.txt>` | Recursively disassembles every function of a Python 3.13 `.pyc` | `pip install xdis` |
| `video_frames.py <workdir>` | Saves one frame per second from `<workdir>/vid/v.mp4` | `pip install opencv-python-headless` |
| `video_contact_sheet.py <workdir> <every_s> <cols> <out.jpg> <t0> <t1>` | Builds a grid of frames with timestamps, to study motion | OpenCV |

**Before disassembling the extracted `main` entry:** prepend a 16-byte Python 3.13 `.pyc` header (`F3 0D 0D 0A` + 12 zero bytes).
