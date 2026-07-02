import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy.install_systemd_service import generate_service


def main():
    template = ROOT / "deploy" / "vision-pose-coach.service.template"
    text = template.read_text(encoding="utf-8")
    assert "WorkingDirectory={{PROJECT_DIR}}" in text
    assert "ExecStart={{PYTHON_BIN}} server_main.py" in text
    assert "Restart=always" in text

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
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
        output_path, _ = generate_service(config, output_dir=tmp_path / "generated")
        rendered = output_path.read_text(encoding="utf-8")
        assert "{{" not in rendered
        assert "User=pi" in rendered
        assert "WorkingDirectory=/home/pi/VisionPoseCoach/WorkSpace" in rendered
        assert "ExecStart=/home/pi/VisionPoseCoach/WorkSpace/.venv/bin/python server_main.py" in rendered

    source = (ROOT / "deploy" / "install_systemd_service.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "did not run systemctl" in source

    print("systemd_deploy_ok")


if __name__ == "__main__":
    main()
