"""Patch models/train.py for Phase 3 ramp and make_env initial DD penalty."""

import sys
from pathlib import Path
p = Path("models/train.py")
if not p.exists():
    print("File not found")
    sys.exit(1)

txt = p.read_text()

# 1. Fix _apply_phase to skip None DD penalties (Phase 3 ramp handles them)
old = """        phase_cfg = CURRICULUM[phase]
        try:
            self.training_env.set_attr("lambda_daily_dd", phase_cfg["lambda_daily_dd"])
            self.training_env.set_attr("lambda_total_dd", phase_cfg["lambda_total_dd"])
            self.training_env.set_attr("lambda_target",   phase_cfg["lambda_target"])
        except Exception:
            pass"""
new = """        phase_cfg = CURRICULUM[phase]
        try:
            # Phase 3 DD penalties are ramped dynamically via _on_step
            if phase_cfg["lambda_daily_dd"] is not None:
                self.training_env.set_attr("lambda_daily_dd", phase_cfg["lambda_daily_dd"])
            if phase_cfg["lambda_total_dd"] is not None:
                self.training_env.set_attr("lambda_total_dd", phase_cfg["lambda_total_dd"])
            self.training_env.set_attr("lambda_target", phase_cfg["lambda_target"])
        except Exception:
            pass"""
txt = txt.replace(old, new)

# 2. Fix make_env to use ramp starting values for Phase 3
old2 = """        env.lambda_daily_dd = phase_cfg["lambda_daily_dd"]
        env.lambda_total_dd = phase_cfg["lambda_total_dd"]
        env.lambda_target   = phase_cfg["lambda_target"]"""
new2 = """        if phase == 3:
            env.lambda_daily_dd = PHASE3_RAMP["lambda_daily_dd_start"]
            env.lambda_total_dd = PHASE3_RAMP["lambda_total_dd_start"]
        else:
            env.lambda_daily_dd = phase_cfg["lambda_daily_dd"]
            env.lambda_total_dd = phase_cfg["lambda_total_dd"]
        env.lambda_target = phase_cfg["lambda_target"]"""
txt = txt.replace(old2, new2)

# 3. Also rewrite the advance print to show ramped values explicitly for Phase 3
old3 = """                print(f"     lambda_daily_dd={phase_cfg['lambda_daily_dd']}  "
                      f"lambda_total_dd={phase_cfg['lambda_total_dd']}  "
                      f"lr={phase_cfg['learning_rate']}\n")"""
new3 = """                if self.phase == 3:
                    print(f"     lambda_daily_dd=ramped 0.050→0.150  "
                          f"lambda_total_dd=ramped 0.080→0.150  "
                          f"lr={phase_cfg['learning_rate']}\n")
                else:
                    print(f"     lambda_daily_dd={phase_cfg['lambda_daily_dd']}  "
                          f"lambda_total_dd={phase_cfg['lambda_total_dd']}  "
                          f"lr={phase_cfg['learning_rate']}\n")"""
txt = txt.replace(old3, new3)

p.write_text(txt)
print("Patch applied successfully")
