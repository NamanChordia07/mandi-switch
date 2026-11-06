"""ganesh-sales — Shree Ganesh Fasteners' sales agent (owned by Sanjay Patil). Pushy; always upsells volume."""
from agents.vendors.common import VendorAgent, main
from core.money import fmt_unit, to_paise


class GaneshSales(VendorAgent):
    def cover_note(self) -> str:
        return "Best rate in the market — take the full lot and save big!"

    def upsell(self) -> str:
        head = to_paise(self.rules_doc["quote"]["unit_price"])
        return f"Honestly, take 50,000 pcs and you get {fmt_unit(head)} — you will need them anyway!"


if __name__ == "__main__":
    main("ganesh", GaneshSales)
