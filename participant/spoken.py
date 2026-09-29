"""Deterministic speech for the twelve public tool result contracts.

No planner prose, session state or evaluator data belongs here. Unknown shapes
return None so the controller keeps its field-labelled receipt. In particular,
the public price fields do not specify a currency: never append a guessed unit.
"""
from decimal import Decimal
import math


PUBLIC_TOOLS = {
    "search_flights": {"status", "flights"},
    "book_flight": {"status", "booking_ref", "passenger"},
    "update_identity_doc": {"status", "updated_doc", "masked_number"},
    "get_card_benefits": {"status", "card_type", "benefits"},
    "get_exchange_rate": {"status", "converted_amount", "rate"},
    "modify_autopay": {"status", "autopay_enabled", "bill", "source"},
    "search_apartments": {"status", "city", "results"},
    "calculate_commute": {"status", "duration_mins", "mode"},
    "update_search_filter": {"status", "filter_updated", "new_value"},
    "track_order": {"status", "order_id", "shipping_status"},
    "search_products": {"status", "products"},
    "add_to_cart": {"status", "product_id", "quantity", "cart_total"},
}

_CURRENCIES = {
    "USD": ("US dollar", "US dollars"), "EUR": ("euro", "euros"),
    "GBP": ("British pound", "British pounds"), "INR": ("Indian rupee", "Indian rupees"),
    "JPY": ("Japanese yen", "Japanese yen"), "CNY": ("Chinese yuan", "Chinese yuan"),
    "CAD": ("Canadian dollar", "Canadian dollars"), "AUD": ("Australian dollar", "Australian dollars"),
    "CHF": ("Swiss franc", "Swiss francs"),
}


def _text(value, *, label=False):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "[]{};"):
        raise ValueError("Expected plain nonempty text")
    # Labels use the contract's snake_case names. Identifiers keep underscores
    # audible rather than silently turning one identifier into another.
    return " ".join(value.replace("_", " " if label else " underscore ").replace("%", " percent").split())


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Expected a finite number, not a boolean or formatted string")
    # No currency rounding or arithmetic: preserve the actual returned value.
    text = format(Decimal(str(value)), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _money(value, currency):
    code = _text(currency).upper()
    singular, plural = _CURRENCIES.get(code, (code, code))
    return f"{_number(value)} {singular if abs(value) == 1 else plural}"


def _same(result, result_key, args, arg_key):
    value, supplied = result[result_key], args[arg_key]
    if type(value) is not type(supplied) or value != supplied:
        raise ValueError("Result does not confirm the supplied argument")
    return value


def _rows(result, key, fields):
    rows = result[key]
    if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != fields for row in rows):
        raise ValueError("Unexpected result records")
    return rows


def spoken_result(name, args, result):
    """Return a complete receipt, or None for the existing factual fallback."""
    if (name not in PUBLIC_TOOLS or not isinstance(args, dict) or not isinstance(result, dict)
            or result.get("status") != "success" or set(result) != PUBLIC_TOOLS[name]):
        return None
    try:
        if name == "track_order":
            order = _text(_same(result, "order_id", args, "order_id"))
            status = _text(result["shipping_status"], label=True)
            return f"Order {order} has shipping status: {status[0].lower() + status[1:]}."
        if name == "get_exchange_rate":
            source = _money(args["amount"], args["from_currency"])
            target = _money(result["converted_amount"], args["to_currency"])
            return f"{source} is {target}, at a rate of {_number(result['rate'])}."
        if name == "calculate_commute":
            mode = _text(result["mode"], label=True)
            if "mode" in args:
                _same(result, "mode", args, "mode")
            origin, destination = _text(args["origin_address"]), _text(args["destination_address"])
            duration = _number(result["duration_mins"])
            unit = "minute" if result["duration_mins"] == 1 else "minutes"
            journey = (f"{mode.capitalize()} from {origin} to {destination}" if mode in {"walking", "driving", "cycling"}
                       else f"The commute from {origin} to {destination} by {mode}")
            return f"{journey} takes {duration} {unit}."
        if name == "get_card_benefits":
            card = _text(_same(result, "card_type", args, "card_type"), label=True)
            benefits = result["benefits"]
            if not isinstance(benefits, list):
                return None
            items = [_text(item) for item in benefits]
            if not items:
                return f"No benefits were returned for the {card} card."
            listed = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
            return f"The {card} card benefits are {listed}."
        if name == "book_flight":
            passenger = _text(_same(result, "passenger", args, "passenger_name"))
            return f"Done. I booked a flight for {passenger}. Your booking reference is {_text(result['booking_ref'])}."
        if name == "update_identity_doc":
            doc = _text(_same(result, "updated_doc", args, "doc_type"), label=True)
            number = _text(args["doc_number"])
            if result["masked_number"] != args["doc_number"][-4:]:
                return None
            return f"Done. Your {doc} number is updated to {number}."
        if name == "modify_autopay":
            bill = _text(_same(result, "bill", args, "bill_type"), label=True)
            source = _text(_same(result, "source", args, "source_account"))
            if result["autopay_enabled"] is not True:
                return None
            return f"Done. Your {bill} autopay now pulls from {source}."
        if name == "update_search_filter":
            field = _text(_same(result, "filter_updated", args, "filter_name"), label=True)
            value = _same(result, "new_value", args, "value")
            # The public callable accepts a string; unusual structured values
            # belong in the field-labelled fallback, not invented prose.
            return f"Done. Your {field} search filter is now {_text(value)}."
        if name == "add_to_cart":
            product = _text(_same(result, "product_id", args, "product_id"))
            quantity = result["quantity"]
            if type(quantity) is not int:
                return None
            if "quantity" in args:
                _same(result, "quantity", args, "quantity")
            return (f"Done. I added {_number(quantity)} of {product} to your cart. "
                    f"Your cart total is {_number(result['cart_total'])}.")
        if name == "search_flights":
            destination, date = _text(args["destination"]), _text(args["date"])
            rows = _rows(result, "flights", {"flight_id", "destination", "date", "price"})
            parts = []
            for row in rows:
                _same(row, "destination", args, "destination")
                _same(row, "date", args, "date")
                parts.append(f"I found flight {_text(row['flight_id'])} to {destination} on {date}, priced at {_number(row['price'])}.")
            return " ".join(parts) if parts else f"No flights were returned for {destination} on {date}."
        if name == "search_apartments" and not {"city", "bedrooms", "max_price"} <= set(args):
            # A search run with an unstated filter says so instead of implying one.
            where = f" in {_text(_same(result, 'city', args, 'city'))}" if "city" in args else ""
            size = f"{_number(args['bedrooms'])}-bedroom apartments" if "bedrooms" in args else "apartments"
            budget = f" with a maximum monthly rent of {_number(args['max_price'])}" if "max_price" in args else ""
            unstated = [label for key, label in (("city", "city"), ("bedrooms", "bedroom count"), ("max_price", "budget"))
                        if key not in args]
            rows = _rows(result, "results", {"id", "price", "beds"})
            # Only when the result itself confirms the filter was unspecified.
            if ("max_price" not in args or "city" not in args and result["city"] is not None
                    or "bedrooms" not in args and any(row["beds"] is not None for row in rows)):
                raise ValueError("Result does not confirm an unspecified filter")
            parts = [f"I searched for {size}{where}{budget}, with no {' or '.join(unstated)} specified."]
            for row in rows:
                beds = f" with {_number(row['beds'])} bedrooms" if row["beds"] is not None else ""
                parts.append(f"I found apartment {_text(row['id'])}{beds}, at a monthly rent of {_number(row['price'])}.")
            return " ".join(parts) + (" No apartments were returned." if not rows else "")
        if name == "search_apartments":
            city = _text(_same(result, "city", args, "city"))
            bedrooms, budget = _number(args["bedrooms"]), _number(args["max_price"])
            rows = _rows(result, "results", {"id", "price", "beds"})
            parts = [f"I searched {city} for {bedrooms} bedrooms with a maximum monthly rent of {budget}."]
            for row in rows:
                parts.append(f"I found apartment {_text(row['id'])} with {_number(row['beds'])} bedrooms, at a monthly rent of {_number(row['price'])}.")
            return " ".join(parts) + (" No apartments were returned." if not rows else "")
        if name == "search_products":
            query = _text(args["query"])
            budget = f" with a maximum price of {_number(args['max_price'])}" if args.get("max_price") is not None else ""
            rows = _rows(result, "products", {"product_id", "name", "price"})
            parts = [f"I searched for {query}{budget}."]
            for row in rows:
                parts.append(f"I found {_text(row['name'])}, product {_text(row['product_id'])}, priced at {_number(row['price'])}.")
            return " ".join(parts) + (" No products were returned." if not rows else "")
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None
