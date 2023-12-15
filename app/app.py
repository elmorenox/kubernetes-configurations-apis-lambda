"""
Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

import logging
import os
import subprocess
import jinja2
from jinja2 import select_autoescape
import sys


# Logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Jinja configs
templateLoader = jinja2.FileSystemLoader(searchpath="./")
templateEnv = jinja2.Environment(
    autoescape=select_autoescape(default_for_string=True, default=True),
    loader=templateLoader,
    trim_blocks=True,
)


def get_stdout(output):
    """
    Validates command output returncode and returns stdout
    :param output: the output of a subprocess
    :return the stdout of the subprocess output
    """
    logger.info(output)
    if output.returncode == 0:
        command_output = output.stdout
    else:
        raise Exception(
            f"Command failed for - stderr: {output.stderr} - "
            f"returncode: {output.returncode}"
        )

    return command_output


def create_kubeconfig(region, cluster_name):
    """
    Updates the kubernetes context on the `kubeconfig` file.
    :param cluster_name: the name of the EKS cluster
    """
    logger.info("Create kube config file.")
    configure_cli = f"aws eks update-kubeconfig --region {region} --name {cluster_name}"
    output = subprocess.run(
        f"{configure_cli}",
        encoding="utf-8",
        capture_output=True,
        shell=True,
        check=False,
    )
    if output.returncode != 0:
        raise RuntimeError(f"Failed to create kube config file {output.stderr}.")

    logger.info("Successfully created kubeconfig file.")


def update_config_map(ip):
    """
    Updates the `redis.conf` in the ConfigMap with the new IP.
    :param ip: the new IP
    """
    template_file = "templates/redis-config.yaml.jinja"
    template = templateEnv.get_template(template_file)
    config = template.render(ip=ip)
    command = f"cat <<EOF | kubectl apply -f -\n{config}\nEOF"
    output = subprocess.run(
        args=command, encoding="utf-8", capture_output=True, shell=True, check=False
    )
    logger.info("command output: %s", output)
    if output.returncode != 0:
        raise RuntimeError(f"Failed to update ConfigMap: {output.stderr}.")
    logger.info("Successfully updated ConfigMap.")


def delete_pod(pod_name):
    """
    Deletes a pod.
    :param pod_name: the name of the pod to delete
    """
    command = f"kubectl delete pod {pod_name}"
    output = subprocess.run(
        args=command, encoding="utf-8", capture_output=True, shell=True, check=False
    )
    if output.returncode != 0:
        raise RuntimeError(f"Failed to delete pod: {output.stderr}.")

    logger.info("Successfully deleted pod.")


def get_pod_ip(pod_name):
    """
    Gets the IP of a pod.
    :param pod_name: the name of the pod to get the IP
    """
    command = f"kubectl get pod {pod_name} -o=jsonpath='{{.status.podIP}}'"
    output = subprocess.run(
        args=command, encoding="utf-8", capture_output=True, shell=True, check=False
    )
    if output.returncode != 0:
        raise RuntimeError(f"Failed to get pod IP: {output.stderr}.")

    logger.info("Successfully got pod IP.")
    return output.stdout


def handler(event, _):
    """
    Entry point for the lambda.
    :param event: the CFN event
    :param context: the lambda context
    """
    kube_config_path = "/tmp/kubeconfig"
    os.environ["KUBECONFIG"] = kube_config_path

    ip = event["ResourceProperties"].get("IP")

    if not ip:
        try:
            create_kubeconfig("us-east-1", "cluster01")
        except Exception:
            logger.error("Failed to create kubeconfig file")
            sys.exit(1)

        try:
            ip = get_pod_ip("redis-leader-0")
        except Exception:
            logger.error("Failed to get pod IP")
            sys.exit(1)

        try:
            create_kubeconfig("us-west-1", "cluster02")
        except Exception:
            logger.error("Failed to create kubeconfig file")
            sys.exit(1)

        try:
            update_config_map(ip)
            delete_pod("redis-follower-0")
        except Exception:
            logger.error("Signaling failure")
            sys.exit(1)
    else:
        try:
            create_kubeconfig("us-west-1", "cluster02")
        except Exception:
            logger.error("Failed to create kubeconfig file")
            sys.exit(1)

        try:
            update_config_map(ip)
        except Exception:
            logger.error("Signaling failure")
            sys.exit(1)
