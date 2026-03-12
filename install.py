import launch

if not launch.is_installed("yaml"):
    launch.run_pip("install pyyaml", "pyyaml for wildcard-creator")

if not launch.is_installed("requests"):
    launch.run_pip("install requests", "requests for wildcard-creator")

if not launch.is_installed("bs4"):
    launch.run_pip("install beautifulsoup4", "beautifulsoup4 for wildcard-creator")
