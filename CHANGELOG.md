# Changelog

## [Unreleased]

### Added

- **Edit Experiment Button**: Added the ability to edit existing experiments after creation.
  - New "Edit Experiment" button in the Dashboard Overview tab
  - Opens the wizard with pre-loaded experiment configuration
  - Allows modifying simulation settings, LLM parameters, treatment groups, and schedule
  - Experiment ID remains locked (cannot be changed)
  - Tokens are preserved when editing (no regeneration required)

### Backend Changes

- Added `PUT /admin/config/{experiment_id}` endpoint for updating experiment configurations
- Added `update_experiment_config()` function in `config_repo.py` for database updates
- Added CORS support for PUT method

### Frontend Changes

- Added `updateConfig()` function in `admin-api.ts`
- Added `onEditExperiment` prop to Dashboard component
- Added `isEditing` state management in AdminPanel
- Modified StepExperiment to disable experiment ID field when editing
- Skip token validation step when editing existing experiments

### Fixed

- CORS error when making PUT requests (added PUT to allowed methods)

---

## How to Use Edit Feature

1. Go to the Admin Dashboard
2. Select an experiment from the dropdown
3. In the Overview tab, click "Edit Experiment"
4. Modify any parameters in the wizard steps
5. Click "Save" to apply changes

### Notes

- The Experiment ID cannot be changed after creation
- Existing tokens are preserved when editing
- LLM tests are marked as passed when editing (previously validated)
- Changes take effect immediately after saving
