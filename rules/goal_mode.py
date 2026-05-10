"""Goal mode for multi-agent group chat.

When /goal is activated:
  1. User sets the final goal
  2. Admin profile decomposes the goal into sub-tasks
  3. Admin @mentions appropriate profiles to assign tasks
  4. Each profile completes its task and reports back
  5. Admin synthesizes results and reports to user
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Goal:
    goal_id: str = ""
    title: str = ""
    description: str = ""
    created_by: str = "user"
    created_at: str = ""
    status: str = "active"  # active | completed | failed
    tasks: list[dict] = field(default_factory=list)


@dataclass
class GoalMode:
    """Manages goal-oriented task decomposition and distribution."""

    active: bool = False
    current_goal: Optional[Goal] = None
    goal_history: list[Goal] = field(default_factory=list)

    def set_goal(self, title: str, created_by: str = "user") -> Goal:
        """Set a new goal and activate goal mode."""
        goal = Goal(
            goal_id=datetime.now().strftime("goal_%Y%m%d_%H%M%S"),
            title=title,
            description=title,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            status="active",
        )
        self.current_goal = goal
        self.active = True
        return goal

    def add_task(self, task_id: str, description: str, assignee: str = "", requirements: list = None) -> dict:
        """Add a sub-task to the current goal."""
        if not self.current_goal:
            return {}

        task = {
            "task_id": task_id,
            "description": description,
            "assignee": assignee,
            "requirements": requirements or [],
            "status": "pending",
            "result": "",
        }
        self.current_goal.tasks.append(task)
        return task

    def complete_task(self, task_id: str, result: str) -> bool:
        """Mark a specific task as completed."""
        if not self.current_goal:
            return False

        for task in self.current_goal.tasks:
            if task["task_id"] == task_id:
                task["status"] = "completed"
                task["result"] = result
                return True
        return False

    def complete_goal(self) -> bool:
        """Mark the entire goal as completed."""
        if not self.current_goal:
            return False

        self.current_goal.status = "completed"
        self.goal_history.append(self.current_goal)
        self.current_goal = None
        self.active = False
        return True

    def is_complete(self) -> bool:
        """Check if all tasks in the current goal are completed."""
        if not self.current_goal:
            return True

        if not self.current_goal.tasks:
            return True

        return all(
            task["status"] == "completed" for task in self.current_goal.tasks
        )

    def get_pending_tasks(self) -> list[dict]:
        """Get pending tasks for the current goal."""
        if not self.current_goal:
            return []

        return [
            task for task in self.current_goal.tasks
            if task["status"] == "pending"
        ]

    def get_progress(self) -> str:
        """Get a progress summary."""
        if not self.current_goal:
            return "无活跃目标。"

        total = len(self.current_goal.tasks)
        if total == 0:
            return f"🎯 目标: {self.current_goal.title}\n   (等待 admin 拆解任务)"

        completed = sum(
            1 for task in self.current_goal.tasks if task["status"] == "completed"
        )

        lines = [
            f"🎯 目标: {self.current_goal.title}",
            f"   进度: {completed}/{total}",
        ]
        for task in self.current_goal.tasks:
            status = "✅" if task["status"] == "completed" else "⏳"
            assignee = task.get("assignee", "未分配")
            lines.append(f"   {status} [{task['task_id']}] {task['description']} → @{assignee}")

        return "\n".join(lines)

    def deactivate(self):
        """Deactivate goal mode without completing."""
        if self.current_goal:
            self.current_goal.status = "failed"
            self.goal_history.append(self.current_goal)
            self.current_goal = None
        self.active = False
