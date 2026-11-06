"""deccan-sales — Deccan Bolt Works' sales agent (owned by Asha Rao). Professional, relationship-focused."""
from agents.vendors.common import VendorAgent, main


class DeccanSales(VendorAgent):
    def cover_note(self) -> str:
        return "We value our relationship with Sahyadri Motors and will support your new rear bench line."


if __name__ == "__main__":
    main("deccan", DeccanSales)
