import csv
import sys
import textwrap
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import Store, form, heading, note, table, run, money, rupees


# -------------------- DATA STORAGE --------------------

store = Store(
    Path(__file__).with_name("data.json"),
    {
        "people": [],
        "trips": [],
        "expenses": [],
        "payments": [],
        "active_trip_id": None,
        "viewing_trip_id": None,
        "next_expense_id": 1,
        "next_payment_id": 1,
        "selected_action": "",
        "message": "",
    },
)

for key, default in {
    "people": [],
    "trips": [],
    "expenses": [],
    "payments": [],
    "active_trip_id": None,
    "viewing_trip_id": None,
    "next_expense_id": 1,
    "next_payment_id": 1,
    "selected_action": "",
    "message": "",
}.items():
    store.data.setdefault(key, default)

for trip in store.data["trips"]:
    trip.setdefault("status", "closed")
    trip.setdefault("members", [])
    trip.setdefault("name", "Trip")

existing_expense_ids = [
    int(e.get("id", 0)) for e in store.data["expenses"]
]
store.data["next_expense_id"] = max(
    int(store.data["next_expense_id"]),
    max(existing_expense_ids, default=0) + 1,
)

existing_payment_ids = [
    int(p.get("id", 0)) for p in store.data["payments"]
]
store.data["next_payment_id"] = max(
    int(store.data["next_payment_id"]),
    max(existing_payment_ids, default=0) + 1,
)

store.save()


# -------------------- HELPER FUNCTIONS --------------------

def find_trip(trip_id):
    for trip in store.data["trips"]:
        if str(trip.get("id")) == str(trip_id):
            return trip
    return None


def active_trip():
    trip = find_trip(store.data.get("active_trip_id"))
    if trip and trip.get("status") == "open":
        return trip
    return None


def find_expense(expense_id):
    for expense in store.data["expenses"]:
        if str(expense.get("id")) == str(expense_id):
            return expense
    return None


def expenses_for_trip(trip_id):
    return [
        expense for expense in store.data["expenses"]
        if str(expense.get("trip_id")) == str(trip_id)
    ]


def member_key(members):
    return tuple(sorted(
        str(name).strip().casefold() for name in members
    ))


def matching_trips(trip):
    key = member_key(trip.get("members", []))
    return [
        item for item in store.data["trips"]
        if member_key(item.get("members", [])) == key
    ]


def expense_amount(expense):
    # Support both current and older saved data formats.
    return int(expense.get("amount_paise", expense.get("amount", 0)))


def parse_weights(raw_text, shared_members):
    """Parse optional weights like 'Ravi=1, Raju=2'."""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return {}

    selected = {name.casefold(): name for name in shared_members}
    weights = {}

    for item in raw_text.split(","):
        if "=" not in item:
            raise ValueError(
                "Weights format: Name=weight, Name=weight (example: Ravi=1, Raju=2)."
            )
        name_text, weight_text = item.split("=", 1)
        name = name_text.strip()
        weight_text = weight_text.strip()

        if not name or name.casefold() not in selected:
            raise ValueError(
                "Each weight must belong to a participant selected to share this expense."
            )
        if not weight_text.isdigit() or int(weight_text) <= 0:
            raise ValueError("Each weight must be a positive whole number.")

        canonical_name = selected[name.casefold()]
        if canonical_name in weights:
            raise ValueError("Do not enter the same participant's weight twice.")
        weights[canonical_name] = int(weight_text)

    missing = [name for name in shared_members if name not in weights]
    if missing:
        raise ValueError(
            "Enter a weight for every selected participant: " + ", ".join(missing)
        )
    return weights


def split_amount(amount, members, weights=None):
    """Split paise equally or proportionally, preserving every paise."""
    if not members:
        raise ValueError("Select at least one person.")

    weights = weights or {}
    if not weights:
        base, remainder = divmod(amount, len(members))
        return [
            base + (1 if i < remainder else 0)
            for i in range(len(members))
        ]

    member_weights = [int(weights.get(name, 0)) for name in members]
    if any(weight <= 0 for weight in member_weights):
        # Legacy or malformed records fall back to equal splitting.
        base, remainder = divmod(amount, len(members))
        return [
            base + (1 if i < remainder else 0)
            for i in range(len(members))
        ]

    total_weight = sum(member_weights)
    exact_numerators = [amount * weight for weight in member_weights]
    shares = [value // total_weight for value in exact_numerators]
    remainder = amount - sum(shares)

    # Allocate leftover paise to the largest fractional remainders.
    order = sorted(
        range(len(members)),
        key=lambda i: (exact_numerators[i] % total_weight, -i),
        reverse=True,
    )
    for i in order[:remainder]:
        shares[i] += 1
    return shares


def calculate_balances(trip, combine=False):
    members = trip.get("members", [])
    canonical = {name.casefold(): name for name in members}
    balances = {name: 0 for name in members}

    trips_to_include = matching_trips(trip) if combine else [trip]
    included_ids = {
        str(item.get("id")) for item in trips_to_include
    }

    for expense in store.data["expenses"]:
        if str(expense.get("trip_id")) not in included_ids:
            continue

        amount = expense_amount(expense)
        payer_key = str(expense.get("payer", "")).strip().casefold()
        payer = canonical.get(payer_key)

        if payer is not None:
            balances[payer] += amount

        shared = []
        for name in expense.get("members", []):
            canonical_name = canonical.get(
                str(name).strip().casefold()
            )
            if canonical_name is not None and canonical_name not in shared:
                shared.append(canonical_name)

        # Compatibility with older expense records.
        if not shared:
            shared = list(members)

        if shared:
            weights = expense.get("weights", {})
            # Ignore weights for people not in the canonical shared list.
            weights = {
                canonical.get(str(name).strip().casefold()): int(weight)
                for name, weight in weights.items()
                if canonical.get(str(name).strip().casefold()) in shared
            } if isinstance(weights, dict) else {}
            shares = split_amount(amount, shared, weights)
            for name, share in zip(shared, shares):
                balances[name] -= share

    # Apply payments already recorded in the app.
    for payment in store.data["payments"]:
        if str(payment.get("trip_id")) not in included_ids:
            continue

        payer = canonical.get(
            str(payment.get("payer", "")).strip().casefold()
        )
        receiver = canonical.get(
            str(payment.get("receiver", "")).strip().casefold()
        )
        amount = int(payment.get("amount_paise", payment.get("amount", 0)))

        if payer is not None and receiver is not None:
            balances[payer] += amount
            balances[receiver] -= amount

    return balances


def suggest_settlements(balances):
    debtors = [
        [name, -balance]
        for name, balance in balances.items()
        if balance < 0
    ]
    creditors = [
        [name, balance]
        for name, balance in balances.items()
        if balance > 0
    ]

    result = []
    i = j = 0

    while i < len(debtors) and j < len(creditors):
        debtor, owes = debtors[i]
        creditor, receives = creditors[j]
        amount = min(owes, receives)

        if amount > 0:
            result.append([debtor, creditor, amount])

        debtors[i][1] -= amount
        creditors[j][1] -= amount

        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return result


def set_message(message):
    store.data["message"] = message


def trip_history_rows():
    return [
        [
            item.get("id", ""),
            item.get("name", ""),
            ", ".join(item.get("members", [])),
            item.get("status", ""),
            len(expenses_for_trip(item.get("id"))),
        ]
        for item in store.data["trips"]
    ]


def trip_id_options():
    return [str(item["id"]) for item in store.data["trips"]]


def current_expense_id_options(trip):
    return [
        str(expense["id"])
        for expense in expenses_for_trip(trip["id"])
    ]


# -------------------- PDF GENERATOR --------------------

def create_pdf(lines):
    """Create a basic multi-page PDF using Python built-ins."""
    wrapped = []

    for line in lines:
        parts = textwrap.wrap(
            str(line),
            width=85,
            replace_whitespace=False,
            break_long_words=True,
        )
        wrapped.extend(parts or [""])

    pages = [
        wrapped[i:i + 48]
        for i in range(0, len(wrapped), 48)
    ] or [["Trip Expense Report"]]

    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }

    page_ids = [5 + i * 2 for i in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"
    ).encode("ascii")

    for i, page_lines in enumerate(pages):
        content_id = 4 + i * 2
        page_id = 5 + i * 2
        commands = ["BT", "/F1 10 Tf"]

        for line_no, line in enumerate(page_lines):
            safe_line = (
                line.encode("latin-1", errors="replace")
                .decode("latin-1")
            )
            safe_line = (
                safe_line.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            y = 790 - line_no * 15
            commands.append(
                f"1 0 0 1 45 {y} Tm ({safe_line}) Tj"
            )

        commands.append("ET")
        stream = "\n".join(commands).encode("latin-1")

        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for obj_id in range(1, 4 + len(pages) * 2):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        pdf.extend(objects[obj_id])
        pdf.extend(b"\nendobj\n")

    xref_position = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    pdf.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_position}\n%%EOF"
        ).encode("ascii")
    )

    return bytes(pdf)


# -------------------- PAGE DISPLAY --------------------

def view():
    out = heading("Trip-wise Shared Expense Settler")
    out += note(
        "Manage trip expenses, split costs, view balances, "
        "and record payments."
    )

    message = store.data.get("message", "")
    if message:
        out += note(message)
        store.data["message"] = ""
        store.save()

    # Trip history page.
    if store.data.get("selected_action") == "show_history":
        out += heading("Trip History")
        out += table(
            ["Trip ID", "Trip Name", "Participants", "Status", "Expenses"],
            trip_history_rows(),
        )

        if not store.data["trips"]:
            out += note("No saved trips yet.")

        if store.data["trips"]:
            out += heading("View a Saved Trip")
            out += form(
                "view_history_trip",
                [(
                    "history_trip_id",
                    "Choose Trip ID",
                    "select",
                    trip_id_options(),
                )],
                "View Selected Trip",
            )

        out += form("show_current_trip", [], "Back to Current Trip")
        return out

    viewing_id = store.data.get("viewing_trip_id")
    viewing_history = viewing_id is not None
    trip = find_trip(viewing_id) if viewing_history else active_trip()

    if trip is None:
        out += heading("Create a New Trip")
        out += form(
            "create_trip",
            [
                ("trip_name", "Trip name", "text", ""),
                (
                    "members_text",
                    "Participants (separate names with commas)",
                    "text",
                    "",
                ),
            ],
            "Create Trip",
        )
        out += form("show_history", [], "Trip History")
        return out

    members = trip.get("members", [])
    trip_expenses = expenses_for_trip(trip["id"])
    read_only = viewing_history or trip.get("status") != "open"

    out += heading("Trip: " + trip.get("name", "Trip"))
    out += note("Participants: " + ", ".join(members))

    if read_only:
        out += note(
            "You are viewing a saved or closed trip. Details are read-only."
        )
        out += form("show_current_trip", [], "Back to Current Trip")
        out += form("show_history", [], "Trip History")
    else:
        out += heading("Add an Expense")
        out += form(
            "add_expense",
            [
                ("description", "Expense description", "text", ""),
                ("payer", "Who paid?", "select", members),
                ("amount", "Amount in rupees", "number", ""),
                ("members", "Who shares this expense?", "checkboxes", members),
                ("weights_text", "Optional member weights (Name=weight, comma-separated; blank = equal split)", "optional_text", ""),
            ],
            "Add Expense",
        )

    # Expense history.
    out += heading("Expense History")
    expense_rows = [
        [
            expense.get("id", ""),
            expense.get("description", ""),
            expense.get("payer", ""),
            rupees(expense_amount(expense)),
            ", ".join(expense.get("members", [])),
            ", ".join(
                f"{name}={weight}"
                for name, weight in expense.get("weights", {}).items()
            ) if expense.get("weights") else "Equal",
        ]
        for expense in trip_expenses
    ]
    out += table(
        ["ID", "Description", "Paid By", "Amount", "Shared By", "Split"],
        expense_rows,
    )

    if not trip_expenses:
        out += note("No expenses have been added to this trip.")

    # Individual trip balances.
    out += heading("Trip Balances")
    balances = calculate_balances(trip, combine=False)
    out += table(
        ["Participant", "Balance"],
        [[name, rupees(balance)] for name, balance in balances.items()],
    )
    out += note(
        "Positive balance = should receive money. "
        "Negative balance = owes money."
    )

    # Collapsible combined balances.
    selected = store.data.get("selected_action", "")
    out += heading("Combined Balances for Matching Trips")
    out += form(
        "toggle_combined",
        [],
        "Hide Combined Balances"
        if selected == "show_combined"
        else "Show Combined Balances",
    )

    combined = calculate_balances(trip, combine=True)
    if selected == "show_combined":
        same_group = matching_trips(trip)
        out += note(
            "Included trips: "
            + ", ".join(item.get("name", "Trip") for item in same_group)
        )
        out += table(
            ["Participant", "Combined Balance"],
            [[name, rupees(balance)] for name, balance in combined.items()],
        )

    # Collapsible suggested settlements.
    out += heading("Suggested Settlements")
    out += form(
        "toggle_settlements",
        [],
        "Hide Suggested Settlements"
        if selected == "show_settlements"
        else "Show Suggested Settlements",
    )

    if selected == "show_settlements":
        transfers = suggest_settlements(combined)
        out += table(
            ["Who Pays", "Who Receives", "Amount"],
            [
                [payer, receiver, rupees(amount)]
                for payer, receiver, amount in transfers
            ],
        )
        if not transfers:
            out += note("Everyone is settled. No payments are needed.")

    if read_only:
        out += note("This trip is read-only.")
        out += form("show_history", [], "Back to Trip History")
        return out

    # Manage Expenses dropdown.
    out += heading("Manage Expenses")
    out += form(
        "choose_manage",
        [(
            "manage_option",
            "Choose an option",
            "select",
            [
                "Edit Expense",
                "Delete Expense",
                "Confirm Payment",
                "Export PDF",
            ],
        )],
        "Open Selected",
    )
    out += form("show_history", [], "Trip History")

    selected = store.data.get("selected_action", "")

    if selected == "show_edit":
        out += heading("Edit Expense")
        out += form(
            "edit_expense",
            [
                (
                    "expense_id",
                    "Choose Expense ID",
                    "select",
                    current_expense_id_options(trip),
                ),
                ("description", "New description", "text", ""),
                ("payer", "Who paid?", "select", members),
                ("amount", "New amount in rupees", "number", ""),
                ("members", "Who shares it?", "checkboxes", members),
                ("weights_text", "Optional member weights (Name=weight, comma-separated; blank = equal split)", "optional_text", ""),
            ],
            "Save Changes",
        )

    elif selected == "show_delete":
        out += heading("Delete Expense")
        out += form(
            "delete_expense",
            [(
                "expense_id",
                "Expense ID",
                "select",
                current_expense_id_options(trip),
            )],
            "Delete Expense",
        )

    elif selected == "show_payment":
        out += heading("Confirm Payment")
        out += form(
            "confirm_payment",
            [
                ("payer", "Who paid?", "select", members),
                ("receiver", "Who received the money?", "select", members),
                ("amount", "Payment amount in rupees", "number", ""),
            ],
            "Record Payment",
        )

    elif selected == "show_export":
        out += heading("Export PDF Report")
        out += note("Download a PDF containing trip expenses, balances and payments.")
        out += form("export_pdf", [], "Download PDF Report")

    out += heading("Trip Controls")
    out += form("close_trip", [], "Close This Trip")
    return out


# -------------------- ACTION HANDLER --------------------

def handle(data):
    action = data.get("action", "")

    # Dropdown selection for Manage Expenses.
    if action == "choose_manage":
        options = {
            "Edit Expense": "show_edit",
            "Delete Expense": "show_delete",
            "Confirm Payment": "show_payment",
            "Export PDF": "show_export",
        }
        chosen = data.get("manage_option", "")
        if chosen not in options:
            raise ValueError("Choose a valid Manage Expenses option.")

        store.data["selected_action"] = options[chosen]
        store.save()
        return

    # Toggle the collapsible sections.
    if action in ("toggle_combined", "toggle_settlements"):
        section = (
            "show_combined"
            if action == "toggle_combined"
            else "show_settlements"
        )
        store.data["selected_action"] = (
            "" if store.data.get("selected_action") == section else section
        )
        store.save()
        return

    if action == "show_history":
        store.data["selected_action"] = "show_history"
        store.save()
        return

    if action in ("show_edit", "show_delete", "show_payment", "show_export"):
        store.data["selected_action"] = action
        store.save()
        return

    if action == "show_current_trip":
        store.data["viewing_trip_id"] = None
        store.data["selected_action"] = ""
        store.save()
        return

    if action == "view_history_trip":
        selected_trip = find_trip(data.get("history_trip_id", ""))
        if selected_trip is None:
            raise ValueError("Trip not found.")

        store.data["viewing_trip_id"] = selected_trip["id"]
        store.data["selected_action"] = ""
        store.save()
        return

    # Create a new trip.
    if action == "create_trip":
        trip_name = data.get("trip_name", "").strip()
        raw_members = data.get("members_text", "").strip()

        if not trip_name:
            raise ValueError("Enter a trip name.")

        members = [
            name.strip() for name in raw_members.split(",") if name.strip()
        ]
        unique_members = []
        seen = set()

        for name in members:
            key = name.casefold()
            if key not in seen:
                unique_members.append(name)
                seen.add(key)

        if len(unique_members) < 2:
            raise ValueError("A trip must have at least two participants.")

        trip_id = max(
            [int(item.get("id", 0)) for item in store.data["trips"]],
            default=0,
        ) + 1

        trip = {
            "id": trip_id,
            "name": trip_name,
            "members": unique_members,
            "status": "open",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

        store.data["trips"].append(trip)
        store.data["active_trip_id"] = trip_id
        store.data["viewing_trip_id"] = None
        store.data["people"] = sorted(
            set(store.data["people"] + unique_members),
            key=str.casefold,
        )
        store.data["selected_action"] = ""
        set_message("Trip created successfully.")
        store.save()
        return

    # Select current trip or historical trip.
    viewing_id = store.data.get("viewing_trip_id")
    trip = find_trip(viewing_id) if viewing_id is not None else active_trip()

    if trip is None:
        raise ValueError("Create or select a trip first.")

    if viewing_id is not None:
        raise ValueError("Trips opened from history are read-only.")

    if trip.get("status") != "open":
        raise ValueError("This trip is closed and cannot be modified.")

    members = trip.get("members", [])

    # Add expense.
    if action == "add_expense":
        description = data.get("description", "").strip()
        payer = data.get("payer", "").strip()
        amount = money(data.get("amount", ""))

        shared = data.get("members", [])
        if isinstance(shared, str):
            shared = [shared]
        shared = [name for name in shared if name in members]

        if not description:
            raise ValueError("Enter an expense description.")
        if payer not in members:
            raise ValueError("Choose a valid payer.")
        if not shared:
            raise ValueError("Select people who share this expense.")
        weights = parse_weights(data.get("weights_text", ""), shared)

        store.data["expenses"].append({
            "id": int(store.data["next_expense_id"]),
            "trip_id": trip["id"],
            "description": description,
            "payer": payer,
            "amount_paise": amount,
            "members": shared,
            "weights": weights,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        store.data["next_expense_id"] += 1
        store.data["selected_action"] = ""
        set_message("Expense added successfully.")
        store.save()
        return

    # Edit expense.
    if action == "edit_expense":
        expense = find_expense(data.get("expense_id", ""))
        if expense is None or str(expense.get("trip_id")) != str(trip["id"]):
            raise ValueError("Expense not found in this trip.")

        description = data.get("description", "").strip()
        payer = data.get("payer", "").strip()
        amount = money(data.get("amount", ""))

        shared = data.get("members", [])
        if isinstance(shared, str):
            shared = [shared]
        shared = [name for name in shared if name in members]

        if not description:
            raise ValueError("Enter an expense description.")
        if payer not in members:
            raise ValueError("Choose a valid payer.")
        if not shared:
            raise ValueError("Select people who share this expense.")
        weights = parse_weights(data.get("weights_text", ""), shared)

        expense["description"] = description
        expense["payer"] = payer
        expense["amount_paise"] = amount
        expense["members"] = shared
        expense["weights"] = weights
        store.data["selected_action"] = ""
        set_message("Expense updated successfully.")
        store.save()
        return

    # Delete expense.
    if action == "delete_expense":
        expense = find_expense(data.get("expense_id", ""))
        if expense is None or str(expense.get("trip_id")) != str(trip["id"]):
            raise ValueError("Expense not found in this trip.")

        store.data["expenses"].remove(expense)
        store.data["selected_action"] = ""
        set_message("Expense deleted successfully.")
        store.save()
        return

    # Record a real payment.
    if action == "confirm_payment":
        payer = data.get("payer", "").strip()
        receiver = data.get("receiver", "").strip()
        amount = money(data.get("amount", ""))

        if payer not in members or receiver not in members:
            raise ValueError("Choose valid participants.")
        if payer == receiver:
            raise ValueError("Payer and receiver must be different.")

        store.data["payments"].append({
            "id": int(store.data["next_payment_id"]),
            "trip_id": trip["id"],
            "payer": payer,
            "receiver": receiver,
            "amount_paise": amount,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        store.data["next_payment_id"] += 1
        store.data["selected_action"] = ""
        set_message("Payment recorded successfully.")
        store.save()
        return

    # Export PDF.
    if action == "export_pdf":
        filename = f"trip_{trip['id']}_report.pdf"
        output_path = Path(__file__).with_name(filename)

        lines = [
            "TRIP-WISE SHARED EXPENSE SETTLER",
            "=" * 45,
            f"Trip: {trip.get('name', 'Trip')}",
            f"Trip ID: {trip['id']}",
            f"Participants: {', '.join(members)}",
            f"Status: {trip.get('status', 'open')}",
            "",
            "EXPENSE HISTORY",
            "-" * 45,
        ]

        trip_expenses = expenses_for_trip(trip["id"])
        if trip_expenses:
            for expense in trip_expenses:
                lines.extend([
                    f"Expense ID: {expense.get('id')}",
                    f"Description: {expense.get('description', '')}",
                    f"Paid by: {expense.get('payer', '')}",
                    f"Amount: {rupees(expense_amount(expense))}",
                    f"Shared by: {', '.join(expense.get('members', []))}",
                    "Weights: " + (
                        ", ".join(
                            f"{name}={weight}"
                            for name, weight in expense.get("weights", {}).items()
                        ) if expense.get("weights") else "Equal split"
                    ),
                    "",
                ])
        else:
            lines.append("No expenses recorded.")

        lines.extend(["", "TRIP BALANCES", "-" * 45])
        for name, balance in calculate_balances(trip).items():
            lines.append(f"{name}: {rupees(balance)}")

        lines.extend(["", "SUGGESTED SETTLEMENTS", "-" * 45])
        transfers = suggest_settlements(calculate_balances(trip))
        if transfers:
            for payer, receiver, amount in transfers:
                lines.append(
                    f"{payer} pays {receiver}: {rupees(amount)}"
                )
        else:
            lines.append("Everyone is settled.")

        lines.extend(["", "RECORDED PAYMENTS", "-" * 45])
        trip_payments = [
            payment for payment in store.data["payments"]
            if str(payment.get("trip_id")) == str(trip["id"])
        ]

        if trip_payments:
            for payment in trip_payments:
                lines.append(
                    f"{payment.get('payer')} paid {payment.get('receiver')}: "
                    f"{rupees(int(payment.get('amount_paise', payment.get('amount', 0))))}"
                )
        else:
            lines.append("No payments recorded.")

        output_path.write_bytes(create_pdf(lines))
        store.data["selected_action"] = ""
        store.save()
        return {"download": filename}

    # Close trip and retain it in history.
    if action == "close_trip":
        trip["status"] = "closed"
        store.data["active_trip_id"] = None
        store.data["viewing_trip_id"] = None
        store.data["selected_action"] = ""
        set_message("Trip closed. You can view it from Trip History.")
        store.save()
        return

    raise ValueError("Unknown action.")


# -------------------- START APPLICATION --------------------

if __name__ == "__main__":
    run("Trip Expense Settler", view, handle)
