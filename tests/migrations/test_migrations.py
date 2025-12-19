import os


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))


def test_all_migrations_have_tests():
    """
    Check that all the database migrations have corresponding unit tests. The check is based on the
    assumption that each migration is under `migrations/versions/<revision ID>_<revision name>.py`
    and has a corresponding test file at `tests/migrations/test_migration_<revision ID>.py`.
    """
    # get the list of migrations that do have tests
    tests_file = [
        f
        for f in os.listdir(CURRENT_DIR)
        if os.path.isfile(os.path.join(CURRENT_DIR, f))
    ]
    migrations_with_tests = set()
    for test_file in tests_file:
        try:
            migrations_with_tests.add(
                test_file.split(".py")[0].split("test_migration_")[1]
            )
        except Exception:
            pass

    # get the list of existing DB migrations, and check if they have corresponding tests
    migrations_path = os.path.join(CURRENT_DIR, "../../migrations/versions")
    migration_files = [
        f
        for f in os.listdir(migrations_path)
        if os.path.isfile(os.path.join(migrations_path, f))
    ]
    for migration_file in migration_files:
        revision_id = migration_file.split(".py")[0].split("_")[0]
        assert (
            revision_id in migrations_with_tests
        ), f"Expected migration '{revision_id}' to have a corresponding test file at '{CURRENT_DIR}/test_migration_{revision_id}.py'"
