# Bambu Queue Builder

A simple web tool to combine multiple `.gcode.3mf` plate files into a single printable queue for Bambu Lab printers.

## ⚡ How It Works

This tool uses **literal concatenation mode**:

- Each uploaded `.gcode.3mf` is treated as a complete, self-contained job
- The embedded G-code from each file is appended in order
- Each file can be repeated multiple times
- Nothing is modified, injected, or removed

All printer behavior (startup, homing, heating, cooldown, push-off, etc.) is preserved exactly as sliced in Bambu Studio.

## 🚀 Features

- Upload multiple `.gcode.3mf` files
- Drag-and-drop reorder
- Set custom labels
- Choose number of copies per file
- Generate a combined queue file ready to print

## ⚠️ Important Notes

- This tool does **not** modify G-code
- Each file runs its full start and end routines
- Always verify output before printing
- Not all workflows are compatible with concatenation

## 🖥️ Running Locally

```bash
python3 app.py

## 📜 License

All rights reserved.

This software is provided for personal use only.
You may not copy, modify, redistribute, or use it commercially without permission.

## 💡 Feedback

Have an idea or found a bug?
Use the in-app feedback form.

## ⚠️ Disclaimer

Use at your own risk.
Always verify generated G-code before printing.
