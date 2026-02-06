import os
import csv
import json


def clean_text(text):
    return " ".join(text.split())


def save_csv(data, path):
    # exports data to csv
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if data and isinstance(data[0], dict):
            w.writerow(data[0].keys())
            for r in data:
                w.writerow(r.values())
        else:
            w.writerows(data)


def save_json(data, path):
    # exports data to json
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
