import os, sys

ROOT = r"G:\TeacherFaceAI\teacher_ai\output\named"

renamed, skipped = 0, 0
for dept in sorted(os.listdir(ROOT)):
    dept_path = os.path.join(ROOT, dept)
    if not os.path.isdir(dept_path):
        continue
    for teacher in sorted(os.listdir(dept_path)):
        t_path = os.path.join(dept_path, teacher)
        if not os.path.isdir(t_path):
            continue
        files = [f for f in sorted(os.listdir(t_path))
                 if os.path.isfile(os.path.join(t_path, f))]
        used = set()
        for f in files:
            src = os.path.join(t_path, f)
            base, ext = os.path.splitext(f)
            name = teacher + ext.lower()
            n = 2
            # avoid collisions with existing files and names used in this run
            existing = {x.lower() for x in os.listdir(t_path)}
            while name.lower() in existing or name.lower() in used:
                name = f"{teacher} ({n}){ext.lower()}"
                n += 1
            if f.lower() == name.lower():
                used.add(name.lower())  # same name different case counts as used
                continue
            dst = os.path.join(t_path, name)
            try:
                os.rename(src, dst)
                print(f"{os.path.relpath(src, ROOT)}  ->  {name}")
                renamed += 1
                used.add(name.lower())
            except OSError as e:
                print(f"SKIP {src}: {e}")
                skipped += 1

print(f"\nDone. renamed={renamed} skipped={skipped}")
