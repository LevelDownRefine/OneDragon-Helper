import yaml
with open("99.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)
with open("99_test.yml", "w", encoding="utf-8") as f:
    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
