"""Keep the daily CLI intact while exposing explicit intraday commands."""
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "volatility-charts":
        from .volatility_charts import main as charts_main
        return charts_main()
    if len(sys.argv) > 1 and sys.argv[1] == "volatility":
        from .volatility_cli import main as volatility_main
        return volatility_main()
    if len(sys.argv) > 1 and sys.argv[1] in ("download", "normalize", "inspect-provider"):
        from .provider_cli import main as provider_main
        return provider_main()
    if len(sys.argv) > 1 and sys.argv[1] in ("validate-data", "run", "report"):
        from .cli import main as intraday_main
        return intraday_main()
    if len(sys.argv) > 1 and sys.argv[1] == "daily":
        del sys.argv[1]
    from .daily_cli import main as daily_main
    return daily_main()


if __name__ == "__main__":
    main()
