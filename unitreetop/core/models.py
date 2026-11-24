"""Robot model definitions: DDS family, motor slots and joint names."""
from dataclasses import dataclass, field
from typing import List, Optional

GO = "unitree_go"  # Go2 / Go2W / B2 / B2W / H1 (LowState_ with 20 motor slots)
HG = "unitree_hg"  # G1 / H1-2 (LowState_ with 35 motor slots, separate BMS topic)

_LEGS = ["FR", "FL", "RR", "RL"]
_QUAD = ["{}_{}".format(leg, j) for leg in _LEGS for j in ("hip", "thigh", "calf")]
_WHEELS = ["{}_wheel".format(leg) for leg in _LEGS]


@dataclass
class RobotModel:
    key: str
    name: str
    family: str
    joints: List[Optional[str]] = field(default_factory=list)  # None = unused slot
    legged: str = "quadruped"  # quadruped | humanoid

    @property
    def num_motors(self) -> int:
        return len(self.joints)


MODELS = {
    "go2": RobotModel("go2", "Go2", GO, list(_QUAD)),
    "go2w": RobotModel("go2w", "Go2-W", GO, _QUAD + _WHEELS),
    "b2": RobotModel("b2", "B2", GO, list(_QUAD)),
    "b2w": RobotModel("b2w", "B2-W", GO, _QUAD + _WHEELS),
    "h1": RobotModel("h1", "H1", GO, [
        "R_hip_roll", "R_hip_pitch", "R_knee", "L_hip_roll", "L_hip_pitch", "L_knee",
        "torso", "L_hip_yaw", "R_hip_yaw", None, "L_ankle", "R_ankle",
        "R_shoulder_pitch", "R_shoulder_roll", "R_shoulder_yaw", "R_elbow",
        "L_shoulder_pitch", "L_shoulder_roll", "L_shoulder_yaw", "L_elbow",
    ], "humanoid"),
    "g1": RobotModel("g1", "G1", HG, [
        "L_hip_pitch", "L_hip_roll", "L_hip_yaw", "L_knee", "L_ankle_pitch", "L_ankle_roll",
        "R_hip_pitch", "R_hip_roll", "R_hip_yaw", "R_knee", "R_ankle_pitch", "R_ankle_roll",
        "waist_yaw", "waist_roll", "waist_pitch",
        "L_shoulder_pitch", "L_shoulder_roll", "L_shoulder_yaw", "L_elbow",
        "L_wrist_roll", "L_wrist_pitch", "L_wrist_yaw",
        "R_shoulder_pitch", "R_shoulder_roll", "R_shoulder_yaw", "R_elbow",
        "R_wrist_roll", "R_wrist_pitch", "R_wrist_yaw",
    ], "humanoid"),
    "h1_2": RobotModel("h1_2", "H1-2", HG, [
        "L_hip_yaw", "L_hip_pitch", "L_hip_roll", "L_knee", "L_ankle_pitch", "L_ankle_roll",
        "R_hip_yaw", "R_hip_pitch", "R_hip_roll", "R_knee", "R_ankle_pitch", "R_ankle_roll",
        "torso",
        "L_shoulder_pitch", "L_shoulder_roll", "L_shoulder_yaw", "L_elbow",
        "L_wrist_roll", "L_wrist_pitch", "L_wrist_yaw",
        "R_shoulder_pitch", "R_shoulder_roll", "R_shoulder_yaw", "R_elbow",
        "R_wrist_roll", "R_wrist_pitch", "R_wrist_yaw",
    ], "humanoid"),
}


def guess_model(family: str, active: List[bool]) -> RobotModel:
    """Best-effort model guess from which motor slots carry data.

    Go2 vs B2 (and Go2-W vs B2-W) cannot be told apart from lowstate alone;
    pass --robot to be explicit.
    """
    idx = [i for i, a in enumerate(active) if a]
    top = max(idx) if idx else -1
    if family == GO:
        if top >= 16:
            return MODELS["h1"]
        if top >= 12:
            return MODELS["go2w"]
        return MODELS["go2"]
    # unitree_hg
    if top == 26 and len(active) > 13 and active[13]:
        return MODELS["h1_2"]
    return MODELS["g1"]


# Unitree wireless remote (40-byte blob inside LowState_.wireless_remote)
REMOTE_BUTTONS = ["R1", "L1", "Start", "Select", "R2", "L2", "F1", "F2",
                  "A", "B", "X", "Y", "Up", "Right", "Down", "Left"]
