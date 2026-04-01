# Studyplan deploy + smoke. Source from config.fish to get studyupdate / study-update.
# Example: source /path/to/ACCA-Study-Plan-APP-OSS-/scripts/studyupdate.fish
set -l _su_script_dir (dirname (status filename))
set -l _su_repo_dir (dirname "$_su_script_dir")

function studyupdate
  set -gx STUDYPLAN_SMOKE_TIMEOUT 300
  if test -f "$_su_repo_dir/studyplan_app.py" && test -f "$_su_repo_dir/studyplan_engine.py"
    bash "$_su_script_dir/studyplan-update.sh" $argv
  else
    echo "Repo not found: $_su_repo_dir" >&2
    return 1
  end
end

function study-update
  studyupdate $argv
end
