"""Admin role management for multi-agent group chat.

The admin is a special profile with elevated permissions:
  - Can interrupt any speaker
  - Gets first priority in speech order
  - Can @ anyone to assign tasks
  - In goal mode, responsible for task decomposition and distribution
"""

from dataclasses import dataclass, field


@dataclass
class AdminRole:
    """Manages admin permissions and task delegation."""

    admin_name: str = ""
    has_admin: bool = False

    # Task tracking
    assigned_tasks: dict[str, list[dict]] = field(default_factory=dict)
    # profile_name -> [{"task_id": ..., "goal": ..., "status": ...}, ...]

    def set_admin(self, profile_name: str):
        """Designate a profile as the group admin."""
        self.admin_name = profile_name
        self.has_admin = True

    def remove_admin(self):
        """Remove the current admin."""
        self.admin_name = ""
        self.has_admin = False

    def is_admin(self, profile_name: str) -> bool:
        """Check if a profile is the admin."""
        return self.has_admin and self.admin_name == profile_name

    def assign_task(
        self, task_id: str, goal: str, requirements: list[str], assignee: str
    ) -> dict:
        """Record a task assignment."""
        task = {
            "task_id": task_id,
            "goal": goal,
            "requirements": requirements,
            "assignee": assignee,
            "status": "assigned",
            "result": "",
        }
        if assignee not in self.assigned_tasks:
            self.assigned_tasks[assignee] = []
        self.assigned_tasks[assignee].append(task)
        return task

    def complete_task(self, task_id: str, result: str, assignee: str):
        """Mark a task as completed."""
        if assignee in self.assigned_tasks:
            for task in self.assigned_tasks[assignee]:
                if task["task_id"] == task_id:
                    task["status"] = "completed"
                    task["result"] = result
                    break

    def get_pending_tasks(self) -> list[dict]:
        """Get all pending tasks across all assignees."""
        pending = []
        for assignee, tasks in self.assigned_tasks.items():
            for task in tasks:
                if task["status"] != "completed":
                    pending.append(task)
        return pending

    def get_tasks_for(self, assignee: str) -> list[dict]:
        """Get all tasks for a specific assignee."""
        return self.assigned_tasks.get(assignee, [])

    def all_tasks_completed(self) -> bool:
        """Check if all tasks are completed."""
        if not self.assigned_tasks:
            return True
        for tasks in self.assigned_tasks.values():
            for task in tasks:
                if task["status"] != "completed":
                    return False
        return True

    def summary(self) -> str:
        """Generate a task summary."""
        if not self.assigned_tasks:
            return "暂无任务分配。"

        lines = ["## 任务状态"]
        for assignee, tasks in self.assigned_tasks.items():
            lines.append(f"\n### {assignee}")
            for task in tasks:
                status = "✅" if task["status"] == "completed" else "⏳"
                lines.append(f"- {status} [{task['task_id']}] {task['goal']}")
        return "\n".join(lines)
