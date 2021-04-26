from setuptools import setup, find_packages


setup(
    name="freecad.asm3",
    version="0.0.0dev",
    url="https://github.com/tomster/FreeCAD-lumberjack",
    description="Woodworking workbench for FreeCAD",
    packages=find_packages("src"),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=["freecad.asm3"],
    namespace_packages=["freecad"],
)
