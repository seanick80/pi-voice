from setuptools import setup, find_packages

setup(
    name="ovos-skill-timer",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=["ovos-workshop>=0.0.12", "requests"],
    entry_points={
        "ovos.plugin.skill": [
            "ovos-skill-timer.openvoiceos=ovos_skill_timer:TimerSkill",
        ],
    },
)
