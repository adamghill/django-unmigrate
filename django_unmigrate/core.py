import os
import sys

from django.conf import settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader

from git import Repo
from git.exc import GitCommandError


class GitError(Exception):
    message = ""

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message


def get_targets(database, ref="master"):
    added_targets = get_added_migrations(ref)
    return get_parents_from_targets(added_targets, database)


def get_added_migrations(ref="master"):
    """
    Detect the added migrations when compared to ``ref``, and return them as
    target tuples: (app_name, migration_name)
    """
    try:
        # Getting repo
        pathname = os.path.dirname(sys.argv[0])
        repo = Repo(os.path.abspath(pathname), search_parent_directories=True)
        # Getting diff
        here = set(repo.git.ls_tree("--name-only", "-r", "HEAD").splitlines())
        there = set(repo.git.ls_tree("--name-only", "-r", ref).splitlines())
        # TODO: improve migration detection
        # settings.MIGRATION_MODULES = {app_name: module_location}
        # the previous setting allows for customization, other than that, there is
        # an established default of app_name.migrations
        migration_files = [x for x in here - there if "migrations/" in x]
        # Constructing targets
        return [(f.split(os.sep)[-3], f.split(os.sep)[-1].split(".")[0]) for f in migration_files]
    except GitCommandError as error:
        raise GitError(str(error))


def get_parents_from_targets(targets, database):
    """
    Inspect the migration tree and return the relevant, common parents from the
    given target tuples: (app_name, migration_name)
    """
    connection = connections[database]
    connection.prepare_database()
    loader = MigrationLoader(connection)
    executor = MigrationExecutor(connection)
    plan_dict = {target: set(loader.graph.backwards_plan(target)) for target in targets}
    final_targets = []
    # Detecting overlapping plans
    # Since targets could be nodes of the same path, we need to discard the
    # plans that are subsets of a bigger one
    for target, plan in plan_dict.items():
        if any([plan & iter_plan == plan for iter_plan in plan_dict.values() if iter_plan != plan]):
            # This plan is a subset of an existing plan, so we ignore it
            continue
        final_targets.append(target)
    # We only return the parent node of the same app, to avoid unapplying related
    # migrations from other apps
    return {
        target: [x.key for x in loader.graph.node_map[target].parents if x.key[0] == target[0]]
        for target in final_targets
    }
