from setuptools import setup, find_packages

setup(
    name="futures-research-backtester",
    version="1.0.0",
    packages=find_packages(),
    package_data={"backtester": ["volatility_chart_template.html", "volatility_chart_data.js", "volatility_chart_ui.js", "vendor/*"]},
    python_requires=">=3.12",
    entry_points={"console_scripts": ["backtester=backtester.__main__:main"]},
    extras_require={"test": ["pytest==8.4.2", "jsonschema==4.26.0"], "databento": ["databento==0.87.0"], "charts": ["matplotlib==3.11.2"]},
)
