import html
import secrets
import re
import os
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# -------------------- HTML HELPERS --------------------

def esc(value):
    return html.escape(str(value), quote=True)


def heading(text):
    return "<h2>" + esc(text) + "</h2>"


def note(text):
    return '<p class="note">' + esc(text) + "</p>"


def money(value):
    """Convert rupees into integer paise."""
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount.")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than zero.")

    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Amount can have at most two decimal places.")

    return int(amount * 100)


def rupees(paise):
    return "Rs " + format(Decimal(int(paise)) / 100, ".2f")


# -------------------- TABLE --------------------

def table(headers, rows):
    out = '<div class="table-wrap"><table><thead><tr>'

    for header in headers:
        out += "<th>" + esc(header) + "</th>"

    out += "</tr></thead><tbody>"

    for row in rows:
        out += "<tr>"
        for cell in row:
            out += "<td>" + esc(cell) + "</td>"
        out += "</tr>"

    out += "</tbody></table></div>"
    return out


# -------------------- FORM BUILDER --------------------

def form(action, fields, button_text):
    out = '<form method="post" action="/">'
    out += (
        '<input type="hidden" name="action" value="'
        + esc(action)
        + '">'
    )
    out += '<input type="hidden" name="_csrf" value="{TOKEN}">'
    out += (
        '<input type="hidden" name="_once" value="'
        + secrets.token_urlsafe(16)
        + '">'
    )

    for field in fields:
        name, label, kind, options = field

        if kind == "checkboxes":
            out += "<fieldset><legend>" + esc(label) + "</legend>"
            out += '<div class="check-grid">'

            for option in options:
                out += (
                    '<label class="check-option">'
                    '<input type="checkbox" name="'
                    + esc(name)
                    + '" value="'
                    + esc(option)
                    + '">'
                    + esc(option)
                    + "</label>"
                )

            out += "</div></fieldset>"

        elif kind == "select":
            out += "<fieldset><label>" + esc(label) + "</label>"
            out += '<select name="' + esc(name) + '" required>'

            if not options:
                out += '<option value="">No options available</option>'
            else:
                out += '<option value="" disabled selected>Select an option</option>'

                for option in options:
                    out += (
                        '<option value="'
                        + esc(option)
                        + '">'
                        + esc(option)
                        + "</option>"
                    )

            out += "</select></fieldset>"

        else:
            optional = kind == "optional_text"
            input_type = (
                kind
                if kind in ("text", "number", "date", "email", "optional_text")
                else "text"
            )
            if input_type == "optional_text":
                input_type = "text"
            step = ' step="0.01"' if input_type == "number" else ""
            required_attr = "" if optional else " required"

            out += (
                "<fieldset><label>"
                + esc(label)
                + '</label><input type="'
                + input_type
                + '" name="'
                + esc(name)
                + '"'
                + step
                + required_attr
                + "></fieldset>"
            )

    out += '<button type="submit">' + esc(button_text) + "</button>"
    out += "</form>"
    return out


# -------------------- LOCAL JSON STORAGE --------------------

class Store:
    def __init__(self, path, defaults):
        self.path = Path(path)
        self.data = dict(defaults)

        if self.path.exists():
            import json

            try:
                with self.path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)

                if isinstance(loaded, dict):
                    self.data.update(loaded)

            except (json.JSONDecodeError, OSError) as error:
                raise ValueError(
                    "Could not read data.json. Make a backup and check the file."
                ) from error

    def save(self):
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")

        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)

        temp_path.replace(self.path)


# -------------------- WEB SERVER --------------------

def run(title, view, handle):
    csrf_token = secrets.token_urlsafe(32)
    used_requests = set()

    project_root = Path(__file__).resolve().parent
    report_folder = project_root / "04_expense_settler"

    class Handler(BaseHTTPRequestHandler):

        def send_page(self, content, status=200):
            page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px;
  background: #f1f5f9;
  color: #172033;
  font: 16px/1.5 Arial, sans-serif;
}
main {
  max-width: 900px;
  margin: auto;
  padding: 28px;
  background: white;
  border-radius: 18px;
  box-shadow: 0 8px 30px #17203312;
}
h1 { margin-top: 0; font-size: 28px; }
h2 { margin-top: 28px; font-size: 21px; }
.note { color: #526174; }
form {
  padding: 20px;
  margin: 14px 0 26px;
  background: #f8fafc;
  border: 1px solid #dce4ee;
  border-radius: 14px;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 14px 0;
  min-width: 0;
}
legend, label { font-weight: 600; margin-bottom: 8px; }
input:not([type=checkbox]), select {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  background: white;
  font: inherit;
}
input:focus, select:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 3px #2563eb20;
}
.check-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
}
.check-option {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px;
  border: 1px solid #dbe3ee;
  border-radius: 10px;
  background: white;
  cursor: pointer;
}
.check-option input {
  width: 18px;
  height: 18px;
  accent-color: #2563eb;
}
button {
  margin-top: 12px;
  padding: 12px 18px;
  border: 0;
  border-radius: 10px;
  background: #2563eb;
  color: white;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
button:hover { background: #1d4ed8; }
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0 24px;
}
th, td {
  padding: 12px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}
th { background: #f8fafc; }
.error {
  padding: 12px;
  background: #fff1f2;
  color: #9f1239;
  border-radius: 10px;
}
footer {
  margin-top: 28px;
  color: #64748b;
  font-size: 13px;
}
@media(max-width:600px) {
  body { padding: 10px; }
  main { padding: 16px; }
  h1 { font-size: 23px; }
  form { padding: 14px; }
}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
__CONTENT__
<footer>DAA Project assignment | Local learning app</footer>
</main>
</body>
</html>"""

            page = page.replace("__TITLE__", esc(title))
            page = page.replace("__CONTENT__", content)
            page = page.replace("{TOKEN}", esc(csrf_token))

            body = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/download":
                params = parse_qs(parsed.query)
                filename = params.get("file", [""])[0]

                # Only allow generated PDF report names.
                if not re.fullmatch(r"trip_\d+_report\.pdf", filename):
                    self.send_error(400, "Invalid filename")
                    return

                filepath = report_folder / filename

                try:
                    content = filepath.read_bytes()
                except FileNotFoundError:
                    self.send_error(404, "PDF report not found")
                    return
                except OSError:
                    self.send_error(500, "Could not read PDF report")
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{filename}"',
                )
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
                return

            self.send_page(view())

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))

                if length <= 0 or length > 100000:
                    raise ValueError("Invalid request size.")

                raw = self.rfile.read(length).decode("utf-8")
                parsed = parse_qs(raw, keep_blank_values=True)

                data = {
                    key: values[-1]
                    for key, values in parsed.items()
                }

                # Preserve all selected checkbox values.
                data["members"] = parsed.get("members", [])

                if not secrets.compare_digest(
                    data.get("_csrf", ""), csrf_token
                ):
                    raise ValueError(
                        "Form expired. Refresh the page and try again."
                    )

                request_id = data.get("_once", "")
                if not request_id or request_id in used_requests:
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.end_headers()
                    return

                result = handle(data)

                # Validate the download name before sending any response.
                download_name = None
                if isinstance(result, dict) and result.get("download"):
                    download_name = result["download"]
                    if not re.fullmatch(
                        r"trip_\d+_report\.pdf", download_name
                    ):
                        raise ValueError("Invalid download filename.")

                used_requests.add(request_id)
                self.send_response(303)

                if download_name:
                    self.send_header(
                        "Location",
                        "/download?file=" + download_name,
                    )
                else:
                    self.send_header("Location", "/")

                self.end_headers()

            except (
                ValueError,
                KeyError,
                OSError,
                InvalidOperation,
                UnicodeDecodeError,
            ) as error:
                self.send_page(
                    '<p class="error">' + esc(error) + "</p>" + view(),
                    400,
                )

        def log_message(self, format_string, *args):
            print("Server:", format_string % args)

    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Server running on port {port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()
