import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.install_systemd_service import generate_service


def test_systemd_template_contains_required_fields():
    template = ROOT / "deploy" / "vision-pose-coach.service.template"

    text = template.read_text(encoding="utf-8")

    assert "WorkingDirectory={{PROJECT_DIR}}" in text
    assert "ExecStart={{PYTHON_BIN}} server_main.py" in text
    assert "Restart=always" in text
    assert "WantedBy=multi-user.target" in text


def test_install_script_generates_service_without_systemctl(tmp_path):
    config = tmp_path / "systemd.env"
    config.write_text(
        "\n".join(
            [
                "PROJECT_DIR=/home/pi/VisionPoseCoach/WorkSpace",
                "PYTHON_BIN=/home/pi/VisionPoseCoach/WorkSpace/.venv/bin/python",
                "SERVICE_USER=pi",
                "SERVICE_NAME=vision-pose-coach.service",
            ]
        ),
        encoding="utf-8",
    )

    output_path, _ = generate_service(
        config,
        output_dir=tmp_path / "generated",
    )
    rendered = output_path.read_text(encoding="utf-8")

    assert output_path.name == "vision-pose-coach.service"
    assert "{{PROJECT_DIR}}" not in rendered
    assert "{{PYTHON_BIN}}" not in rendered
    assert "{{USER}}" not in rendered
    assert "User=pi" in rendered
    assert "WorkingDirectory=/home/pi/VisionPoseCoach/WorkSpace" in rendered
    assert "ExecStart=/home/pi/VisionPoseCoach/WorkSpace/.venv/bin/python server_main.py" in rendered


def test_install_script_does_not_execute_system_commands():
    source = (ROOT / "deploy" / "install_systemd_service.py").read_text(encoding="utf-8")

    assert "subprocess" not in source
    assert "os.system" not in source
    assert "systemctl" in source
    assert "did not run systemctl" in source
    assert "/etc/systemd/system" in source
