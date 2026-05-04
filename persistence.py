import json


def save_regions(output_file, regions):
    with open(output_file, "w") as file:
        json.dump(regions, file, indent=2)
