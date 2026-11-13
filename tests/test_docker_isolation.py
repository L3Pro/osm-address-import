import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from osm_address_import.docker_isolation import (
    DB_IMAGE, WEB_COMMAND, WEB_IMAGE, IsolationError, assert_fresh_project,
    verify_cleanup_scope, verify_isolated_docker,
)


PROJECT = "osaka-api-harness-20261112-deadbeef"


def docker_evidence():
    web_name, db_name = PROJECT + "-web-1", PROJECT + "-db-1"
    isolated, frontend = PROJECT + "_isolated", PROJECT + "_frontend"
    app = pathlib.Path(__file__).resolve().parents[1] / "reports" / "runs" / PROJECT / "app"
    port = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "39003"}]}
    web = {
        "Name": "/" + web_name,
        "Image": WEB_IMAGE,
        "Config": {"Labels": {"com.docker.compose.project": PROJECT,
                              "com.docker.compose.service": "web"},
                   "Env": ["DATABASE_URL=postgresql://test-secret@db/openstreetmap",
                           "RAILS_ENV=production", "RACK_ENV=production"],
                   "Cmd": WEB_COMMAND, "WorkingDir": "/app"},
        "State": {"Running": True},
        "HostConfig": {"PortBindings": port, "ExtraHosts": None},
        "NetworkSettings": {"Networks": {isolated: {}, frontend: {}}, "Ports": port},
        "Mounts": [{"Type": "bind", "Source": str(app), "Destination": "/app"},
                   {"Type": "volume", "Name": PROJECT + "_web-storage", "Destination": "/app/storage",
                    "Source": "/var/lib/docker/volumes/" + PROJECT + "_web-storage/_data"}],
    }
    db = {
        "Name": "/" + db_name,
        "Image": DB_IMAGE,
        "Config": {"Labels": {"com.docker.compose.project": PROJECT,
                              "com.docker.compose.service": "db"}},
        "State": {"Running": True},
        "HostConfig": {"PortBindings": {}},
        "NetworkSettings": {"Networks": {isolated: {}}},
        "Mounts": [{"Type": "volume", "Name": PROJECT + "_db-data",
                    "Destination": "/var/lib/postgresql/data",
                    "Source": "/var/lib/docker/volumes/" + PROJECT + "_db-data/_data"}],
    }
    networks = [
        {"Name": isolated, "Internal": True,
         "Labels": {"com.docker.compose.project": PROJECT},
         "Containers": {"web": {"Name": web_name}, "db": {"Name": db_name}}},
        {"Name": frontend, "Internal": False,
         "Labels": {"com.docker.compose.project": PROJECT},
         "Containers": {"web": {"Name": web_name}}},
    ]
    return [web, db], networks


class IsolationGuardTests(unittest.TestCase):
    def verify(self, containers, networks, volumes=None):
        if volumes is None:
            volumes = [{"Name": name, "Driver": "local", "Options": None,
                        "Labels": {"com.docker.compose.project": PROJECT},
                        "Mountpoint": "/var/lib/docker/volumes/" + name + "/_data"}
                       for name in (PROJECT + "_db-data", PROJECT + "_web-storage")]

        def inspect(kind, *names):
            return {"container": containers, "network": networks, "volume": volumes}[kind]

        with patch("osm_address_import.docker_isolation._inspect", side_effect=inspect), \
             patch.object(pathlib.Path, "read_text", return_value='url: <%= ENV.fetch("DATABASE_URL") %>'):
            verify_isolated_docker(PROJECT)

    def test_expected_disposable_project_passes(self):
        self.verify(*docker_evidence())

    def test_live_database_url_and_volume_are_rejected(self):
        containers, networks = docker_evidence()
        containers[0]["Config"]["Env"][0] = "DATABASE_URL=postgresql://secret@osm-api-sandbox-db-1/openstreetmap"
        with self.assertRaises(IsolationError):
            self.verify(containers, networks)
        containers, networks = docker_evidence()
        containers[1]["Mounts"][0]["Name"] = "osm-api-sandbox_db-data"
        with self.assertRaises(IsolationError):
            self.verify(containers, networks)

    def test_port_forward_dns_override_and_extra_network_are_rejected(self):
        for mutation in ("port", "hosts", "network"):
            containers, networks = docker_evidence()
            if mutation == "port":
                containers[0]["HostConfig"]["PortBindings"]["3000/tcp"][0]["HostPort"] = "3003"
            elif mutation == "hosts":
                containers[0]["HostConfig"]["ExtraHosts"] = ["db:127.0.0.1"]
            else:
                containers[0]["NetworkSettings"]["Networks"]["osm-api-sandbox_default"] = {}
            with self.subTest(mutation=mutation), self.assertRaises(IsolationError):
                self.verify(containers, networks)

    def test_image_and_command_overrides_are_rejected(self):
        for mutation in ("image", "command"):
            containers, networks = docker_evidence()
            if mutation == "image":
                containers[0]["Image"] = "sha256:" + "0" * 64
            else:
                containers[0]["Config"]["Cmd"] = ["sh", "-c", "proxy-to-public-api"]
            with self.subTest(mutation=mutation), self.assertRaises(IsolationError):
                self.verify(containers, networks)

    def test_bind_backed_volume_is_rejected(self):
        containers, networks = docker_evidence()
        volumes = [{"Name": name, "Driver": "local", "Options": None,
                    "Labels": {"com.docker.compose.project": PROJECT},
                    "Mountpoint": "/var/lib/docker/volumes/" + name + "/_data"}
                   for name in (PROJECT + "_db-data", PROJECT + "_web-storage")]
        volumes[0]["Options"] = {"type": "none", "device": "/var/lib/docker/volumes/osm-api-sandbox_db-data/_data"}
        with self.assertRaises(IsolationError):
            self.verify(containers, networks, volumes)

    def test_other_project_or_live_container_on_network_is_rejected(self):
        with self.assertRaises(IsolationError):
            verify_isolated_docker("issue15-osaka-prod")
        containers, networks = docker_evidence()
        networks[0]["Containers"]["live"] = {"Name": "osm-api-sandbox-db-1"}
        with self.assertRaises(IsolationError):
            self.verify(containers, networks)

    def test_creation_refuses_existing_project_resources(self):
        with patch("osm_address_import.docker_isolation._project_resources",
                   return_value={"container": set(), "volume": {PROJECT + "_db-data"}, "network": set()}):
            with self.assertRaises(IsolationError):
                assert_fresh_project(PROJECT)

    def test_cleanup_refuses_unexpected_resource(self):
        expected = {"container": {PROJECT + "-web-1", PROJECT + "-db-1"},
                    "volume": {PROJECT + "_db-data", PROJECT + "_web-storage", PROJECT + "_other"},
                    "network": {PROJECT + "_isolated", PROJECT + "_frontend"}}
        with patch("osm_address_import.docker_isolation.verify_isolated_docker"), \
             patch("osm_address_import.docker_isolation._project_resources", return_value=expected):
            with self.assertRaises(IsolationError):
                verify_cleanup_scope(PROJECT)


if __name__ == "__main__":
    unittest.main()
