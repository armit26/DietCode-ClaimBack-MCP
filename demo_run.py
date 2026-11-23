from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mcp_server.auditor import build_gro_draft, build_sla_reminders, run_irdai_audit

console = Console()


def main():
    console.print(
        Panel.fit(
            "[bold white]ClaimBack MCP — Interactive IRDAI 2024 Claims Audit Prototype[/bold white]\n"
            "[cyan]Team Diet Code · wHACKiest 2026 (Track 1: Make MCP Matter)[/cyan]",
            border_style="blue",
        )
    )

    report = run_irdai_audit("CB-204")

    console.print(
        f"\n[bold red]INSURER REPUDIATION (Gmail MCP):[/bold red] "
        f"Case #{report.case_id} · ₹{report.claimed_amount_inr:,} denied (alleged undisclosed pre-existing illness)"
    )
    console.print(
        f"[bold green]DRIVE POLICY SYNC (Drive MCP):[/bold green] "
        f"{report.continuous_coverage_months} continuous months verified (6 annual renewals)\n"
    )

    breach_table = Table(title="Deterministic IRDAI 2024 Rule Audit", show_lines=True)
    breach_table.add_column("Rule ID", style="cyan", no_wrap=True)
    breach_table.add_column("Status", style="bold red")
    breach_table.add_column("Verified Finding")

    for b in report.breaches:
        breach_table.add_row(b.rule_id, b.status, f"{b.finding}\n[dim]{b.citation}[/dim]")
    console.print(breach_table)

    dupe_table = Table(title="RapidFuzz Duplicate Hospital Bill Audit", show_lines=True)
    dupe_table.add_column("Line Item 1")
    dupe_table.add_column("Duplicate Line Item")
    dupe_table.add_column("Match %", style="yellow")
    dupe_table.add_column("Overcharge", style="bold red")

    for d in report.duplicate_charges:
        dupe_table.add_row(d.item_1, d.item_2, f"{d.similarity_score}%", f"₹{d.amount_inr:,}")
    console.print(dupe_table)
    console.print(
        f"[bold yellow]Total Duplicate Bill Overcharge Flagged:[/bold yellow] ₹{report.total_duplicate_overcharge_inr:,}\n"
    )

    console.print(
        Panel(
            f"[bold]EN:[/bold] {report.voice_briefs['EN']}\n\n"
            f"[bold]HI:[/bold] {report.voice_briefs['HI']}\n\n"
            f"[bold]KN:[/bold] {report.voice_briefs['KN']}",
            title="ElevenLabs Voice Co-Pilot Script (EN · हिंदी · ಕನ್ನಡ)",
            border_style="dark_orange",
        )
    )

    locked = build_gro_draft("CB-204", user_approved=False)
    console.print(f"\n[bold red]HITL Gate Check (Before Approval):[/bold red] {locked['status']} — {locked['message']}")

    choice = input("\n[HITL APPROVAL GATE] Approve saving editable GRO Gmail draft + SLA clocks? (y/n): ").strip().lower()
    if choice == "y":
        draft = build_gro_draft("CB-204", user_approved=True)
        slas = build_sla_reminders("CB-204")

        console.print(
            Panel(
                draft["draft_body"],
                title=f"Gmail MCP Output · {draft['status']} ({draft['scope']})",
                border_style="green",
            )
        )
        for r in slas["reminders"]:
            console.print(f"  [green]✓ Calendar MCP:[/green] {r['title']} → [bold]{r['trigger']}[/bold]")
    else:
        console.print("[yellow]Action cancelled by user. Zero emails drafted or sent.[/yellow]")


if __name__ == "__main__":
    main()