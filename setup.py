from setuptools import find_packages, setup

setup(
    name="agentfuse-crawlers",
    version="0.1.0",
    description="Official-source AI provider monitoring with Scrapy Cloud",
    packages=find_packages(),
    package_data={"agentfuse_crawlers": ["data/*.json"]},
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=["Scrapy==2.18.0"],
    entry_points={"scrapy": ["settings = agentfuse_crawlers.settings"]},
)
