from pathlib import Path

from tinysoul.loop.loop import QueryLoop
from tinysoul.context.workspace import Workspace
from tinysoul.prompt.loop import home_loop_system_sources


AGENT_HOME = Path(__file__).parent / "home" / "agent"


def demo_dog_weight_report():
    """
    Demo: Compute combined dog weight and generate a markdown report in workspace.

    Requires GLM_API_KEY or ZHIPU_API_KEY in environment / .env file.
    """
    # Create a workspace directory
    workspace_dir = Path(__file__).parent / "home" / "workspace" / "workspace_demo_dog_weight"
    workspace_dir.mkdir(exist_ok=True)

    ws = Workspace(
        workspace_location=str(workspace_dir.resolve()),
        workspace_desc="Demo workspace for saving query results as markdown files",
    )

    qlm = QueryLoop(
        initial_query=(
            "I have 2 dogs, a border collie and a scottish terrier. "
            "What is their combined weight? Please save the result as a markdown report in the workspace."
        ),
        loop_system=home_loop_system_sources(AGENT_HOME),
        loop_target="Compute combined weight of a border collie and a scottish terrier, then create a markdown report in the workspace",
        available_action_names=[
            "answer",
            "reasoning",
            "calculate",
            "average_dog_weight",
            "scan_workspace",
            "read_file",
            "create_markdown_file",
            "edit_markdown_file",
            "delete_file",
        ],
        workspace=ws,
    )

    result = qlm.query_loop(max_turns=8)


def demo_dynamic_script():
    """
    Demo: LLM writes a custom Python script, registers it as a temporary action,
    and uses it to analyze data in the workspace.

    Workflow:
    1. Pre-populate workspace with data/numbers.csv
    2. LLM calls create_temporary_script to write scripts/analyze_numbers.py
    3. LLM calls register_temporary_script to register "analyze_numbers"
    4. LLM calls analyze_numbers to compute column statistics
    5. LLM calls create_markdown_file to write a report

    Requires GLM_API_KEY or ZHIPU_API_KEY in environment / .env file.
    """
    workspace_dir = Path(__file__).parent / "home" / "workspace" / "workspace_demo_dynamic"
    workspace_dir.mkdir(exist_ok=True)

    # Pre-populate a sample CSV file
    data_dir = workspace_dir / "data"
    data_dir.mkdir(exist_ok=True)
    csv_path = data_dir / "numbers.csv"
    csv_path.write_text(
        "column_a,column_b,column_c\n10,25,8\n20,15,12\n30,35,18\n40,20,22\n50,45,28\n",
        encoding="utf-8",
    )

    ws = Workspace(
        workspace_location=str(workspace_dir.resolve()),
        workspace_desc=(
            "Demo workspace for dynamic script generation. "
            "Contains data/numbers.csv with 3 columns of integers."
        ),
    )

    qlm = QueryLoop(
        initial_query=(
            "I have a CSV file at data/numbers.csv with 3 columns of numbers. "
            "Please write a Python script to analyze it (compute average, max, min for each column), "
            "run the script to get the results, and then save the analysis as a markdown report."
        ),
        loop_system=home_loop_system_sources(AGENT_HOME),
        loop_target=(
            "Analyze data/numbers.csv by creating and running a custom Python script, "
            "then produce a markdown report with the column statistics."
        ),
        available_action_names=[
            "answer",
            "reasoning",
            "scan_workspace",
            "read_file",
            "create_markdown_file",
            "edit_markdown_file",
            "delete_file",
            "create_temporary_script",
            "edit_temporary_script",
            "register_temporary_script",
        ],
        workspace=ws,
    )

    result = qlm.query_loop(max_turns=12)


if __name__ == "__main__":
    import sys

    demos = {
        "dog_weight": demo_dog_weight_report,
        "dynamic_script": demo_dynamic_script,
    }

    if len(sys.argv) > 1 and sys.argv[1] in demos:
        try:
            demos[sys.argv[1]]()
        except KeyboardInterrupt:
            print("\n[Exit] Demo interrupted by user.")
    else:
        print("Usage: python main.py <demo_name>")
        print(f"Available demos: {', '.join(demos.keys())}")
        print("\nExamples:")
        print("  python main.py dog_weight")
        print("  python main.py dynamic_script")
