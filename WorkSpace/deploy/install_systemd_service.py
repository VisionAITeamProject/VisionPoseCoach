import argparse
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEPLOY_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = DEPLOY_DIR / "vision-pose-coach.service.template"
DEFAULT_OUTPUT_DIR = DEPLOY_DIR / "generated"


def parse_env_file(path: Path):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid config line: {raw_line}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def render_service(template_text: str, config: dict):
    required = ["PROJECT_DIR", "PYTHON_BIN", "SERVICE_USER", "SERVICE_NAME"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")

    rendered = template_text
    rendered = rendered.replace("{{USER}}", config["SERVICE_USER"])
    rendered = rendered.replace("{{PROJECT_DIR}}", config["PROJECT_DIR"])
    rendered = rendered.replace("{{PYTHON_BIN}}", config["PYTHON_BIN"])
    return rendered


def generate_service(config_path: Path, template_path: Path = DEFAULT_TEMPLATE, output_dir: Path = DEFAULT_OUTPUT_DIR):
    config = parse_env_file(config_path)
    template_text = template_path.read_text(encoding="utf-8")
    rendered = render_service(template_text, config)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / config["SERVICE_NAME"]
    output_path.write_text(rendered, encoding="utf-8")
    return output_path, config


def main():
    parser = argparse.ArgumentParser(
        description="Render the Vision Pose Coach systemd service file without installing it."
    )
    parser.add_argument(
        "--config",
        default=str(DEPLOY_DIR / "systemd_config.example.env"),
        help="Path to the systemd env config file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kept for clarity. This script always runs as dry-run and never installs the service.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    output_path, config = generate_service(config_path)

    print("Generated service file:")
    print(output_path)
    print()
    print("This script did not copy files to /etc/systemd/system and did not run systemctl.")
    print("Review the generated file first. On the Raspberry Pi, run these commands manually only when ready:")
    print()
    print(f"sudo cp {output_path} /etc/systemd/system/{config['SERVICE_NAME']}")
    print("sudo systemctl daemon-reload")
    print(f"sudo systemctl enable {config['SERVICE_NAME']}")
    print(f"sudo systemctl start {config['SERVICE_NAME']}")
    print(f"sudo systemctl status {config['SERVICE_NAME']}")


if __name__ == "__main__":
    main()
