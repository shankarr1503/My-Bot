"""
Monitor Bot - single entry point for the packaged app.

One executable, three modes:
  * (no args)   open the Dashboard GUI (the default)
  * --bot       run the Telegram bot (the Dashboard launches the app this way)
  * --setup     run the console setup wizard (from source only)

This lets the whole thing ship as one MonitorBotDashboard.exe: the window the
user sees is the dashboard, and when they press Start it runs this same exe
again with --bot, so there's no second file to find and no stray console.

In the packaged (windowed) build there is no console, so the console wizard
can't read input there - --setup just opens the Dashboard, whose Connect tab
is the GUI equivalent. From source, --setup still runs the console wizard.
"""

import sys


def main():
    args = sys.argv[1:]
    if "--bot" in args:
        import monitor_bot
        monitor_bot.main()
    elif "--setup" in args and not getattr(sys, "frozen", False):
        import setup_wizard
        setup_wizard.main()
    else:
        import bot_dashboard
        bot_dashboard.main()


if __name__ == "__main__":
    main()
