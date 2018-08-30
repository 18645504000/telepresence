# Copyright 2018 Datawire. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from json import loads, dump
from subprocess import CalledProcessError
from typing import Dict, Tuple, List

from telepresence.proxy.remote import RemoteInfo
from telepresence.runner import Runner


def _get_remote_env(runner: Runner, pod_name: str,
                    container_name: str) -> Dict[str, str]:
    """Get the environment variables in the remote pod."""
    env = runner.get_output(
        runner.kubectl(
            "exec", pod_name, "--container", container_name, "--", "python3",
            "-c", "import json, os; print(json.dumps(dict(os.environ)))"
        )
    )
    result = {}  # type: Dict[str,str]
    result.update(loads(env))
    return result


def get_env_variables(runner: Runner,
                      remote_info: RemoteInfo) -> Dict[str, str]:
    """
    Generate environment variables that match kubernetes.
    """
    # Get the environment:
    remote_env = _get_remote_env(
        runner, remote_info.pod_name, remote_info.container_name
    )
    # Tell local process about the remote setup, useful for testing and
    # debugging:
    result = {
        "TELEPRESENCE_POD": remote_info.pod_name,
        "TELEPRESENCE_CONTAINER": remote_info.container_name
    }
    # Alpine, which we use for telepresence-k8s image, automatically sets these
    # HOME, PATH, HOSTNAME. The rest are from Kubernetes:
    for key in ("HOME", "PATH", "HOSTNAME"):
        if key in remote_env:
            del remote_env[key]
    result.update(remote_env)
    return result


def get_remote_env(runner: Runner, remote_info: RemoteInfo) -> Dict[str, str]:
    """
    Get the environment variables we want to copy from the remote pod
    """
    span = runner.span()
    try:
        # It may take a few seconds for the SSH proxies to get going:
        for _ in runner.loop_until(10, 0.25):
            try:
                return get_env_variables(runner, remote_info)
            except CalledProcessError:
                pass
        raise runner.fail("Error: Failed to get environment variables")
    finally:
        span.end()


def _serialize_as_env_file(env: Dict[str, str]) -> Tuple[str, List[str]]:
    """
    Render an env file as defined by Docker Compose
    https://docs.docker.com/compose/env-file/

    - Compose expects each line in an env file to be in VAR=VAL format.
    - Lines beginning with # are processed as comments and ignored.
    - Blank lines are ignored.
    - There is no special handling of quotation marks.
      This means that they are part of the VAL.

    Unstated but implied is that values cannot include newlines.
    """
    res = []
    skipped = []
    for key, value in sorted(env.items()):
        if "\n" in value:
            skipped.append(key)
        else:
            res.append("{}={}\n".format(key, value))
    return "".join(res), skipped


def write_env_file(runner: Runner, env: Dict[str, str], env_file: str) -> None:
    try:
        data, skipped = _serialize_as_env_file(env)
        with open(env_file, "w") as env_file_file:
            env_file_file.write(data)
        if skipped:
            runner.show(
                "Skipped these environment keys when writing env "
                "file because the associated values have newlines:"
            )
            for key in skipped:
                runner.show(key)
    except IOError as exc:
        runner.show("Failed to write environment as env file: {}".format(exc))


def write_env_json(runner: Runner, env: Dict[str, str], env_json: str) -> None:
    try:
        with open(env_json, "w") as env_json_file:
            dump(env, env_json_file, sort_keys=True, indent=4)
    except IOError as exc:
        runner.show("Failed to write environment as JSON: {}".format(exc))


def setup(_: Runner, args):
    def write_env_files(runner_: Runner, env: Dict[str, str]):
        if args.env_json:
            write_env_json(runner_, env, args.env_json)
        if args.env_file:
            write_env_file(runner_, env, args.env_file)

    return get_remote_env, write_env_files
