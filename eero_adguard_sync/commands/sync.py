import ipaddress
import fnmatch
import re
import click
from requests import HTTPError
from timeit import default_timer as timer

from eero_adguard_sync.client import EeroClient, AdGuardClient
from eero_adguard_sync.models import (
    AdGuardCredentialSet,
    AdGuardClientDevice,
    DHCPClient,
    DHCPClientTable,
    DHCPClientTableDiff,
)


NETWORK_SELECT_PROMPT = """Multiple Eero networks found, please select by ID
                
{network_options}

Network ID"""


def _parse_multi_env(value: tuple[str, ...]) -> tuple[str, ...]:
    """Expand comma-separated values that arrive as a single env var string."""
    result = []
    for item in value:
        result.extend(v.strip() for v in item.split(",") if v.strip())
    return tuple(result)


def _match_pattern(candidate: str, pattern: str) -> bool:
    """Match a candidate string against a pattern.
    Patterns prefixed with 're:' are treated as Python regex; others use fnmatch."""
    if pattern.startswith("re:"):
        return bool(re.search(pattern[3:], candidate))
    return fnmatch.fnmatch(candidate, pattern)


class EeroAdGuardSyncHandler:
    def __init__(self, eero_client: EeroClient, adguard_client: AdGuardClient):
        self.eero_client = eero_client
        self.adguard_client = adguard_client
        self.__network = self.__prompt_network()

    @property
    def network(self) -> str:
        return self.__network

    def __prompt_network(self) -> str:
        network_list = self.eero_client.account()["networks"]["data"]
        network_count = len(network_list)
        if not network_list:
            raise click.ClickException("No Eero networks associated with this account")
        network_idx = 0
        if network_count > 1:
            network_options = "\n".join(
                [f"{i}: {network['name']}" for i, network in enumerate(network_list)]
            )
            choice = click.Choice([str(i) for i in range(network_count)])
            network_idx = int(
                click.prompt(
                    NETWORK_SELECT_PROMPT.format(network_options=network_options),
                    type=choice,
                    default=str(network_idx),
                    show_choices=False,
                )
            )
        network = network_list[network_idx]
        click.echo(f"Selected network '{network['name']}'")
        return network["url"]

    def _is_excluded(
        self,
        device: DHCPClient,
        exclude_ranges: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
        exclude_ids: set[str],
    ) -> bool:
        patterns = [i.lower() for i in exclude_ids]
        candidates = [
            str(device.mac_address).lower(),
            (device.nickname or "").lower(),
            (device.hostname or "").lower(),
        ]
        for candidate in candidates:
            for pattern in patterns:
                if _match_pattern(candidate, pattern):
                    return True
        for iface in device.ip_interfaces:
            for network in exclude_ranges:
                if iface.ip in network:
                    return True
        return False

    def _is_no_global(self, device: DHCPClient, no_global_ids: set[str]) -> bool:
        """Return True if the device's nickname matches any --no-global-id pattern."""
        if not no_global_ids:
            return False
        nickname = (device.nickname or "").lower()
        patterns = [i.lower() for i in no_global_ids]
        return any(_match_pattern(nickname, p) for p in patterns)

    def create(
        self,
        diff: DHCPClientTableDiff,
        conflicting_nicknames: set[str] = None,
        claimed_ids: set[str] = None,
        no_global_ids: set[str] = None,
    ):
        if not diff.discovered:
            click.echo("No new clients found, skipped creation")
            return
        conflicting_nicknames = {n.lower() for n in (conflicting_nicknames or set())}
        running_claimed = set(claimed_ids or set())
        no_global_ids = no_global_ids or set()
        with click.progressbar(
            diff.discovered, label="Add new clients", show_pos=True
        ) as bar:
            for eero_device in bar:
                use_global = not self._is_no_global(eero_device, no_global_ids)
                device = AdGuardClientDevice.from_dhcp_client(
                    eero_device,
                    exclude_ids=conflicting_nicknames | running_claimed,
                    use_global_settings=use_global,
                )
                running_claimed.update(i.lower() for i in device.ids)
                try:
                    self.adguard_client.add_client_device(device)
                except HTTPError as e:
                    errors = [
                        "client already exists",
                        "another client uses the same id",
                        "another client uses the same name",
                    ]
                    if any(error.lower() in e.response.text.lower() for error in errors):
                        click.secho(
                            f"Warning: skipped '{eero_device.nickname}' [{eero_device.mac_address}]"
                            f" — identifier conflict with existing AdGuard client",
                            fg="yellow",
                        )
                    else:
                        click.secho(
                            f"Warning: failed to add '{eero_device.nickname}' "
                            f"[{eero_device.mac_address}]: {e.response.text}",
                            fg="yellow",
                        )

    def update(
        self,
        diff: DHCPClientTableDiff,
        conflicting_nicknames: set[str] = None,
        no_global_ids: set[str] = None,
        exclude_ranges: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = None,
        exclude_ids: set[str] = None,
    ):
        if not diff.associated:
            click.echo("No existing clients found, skipped update")
            return
        conflicting_nicknames = {n.lower() for n in (conflicting_nicknames or set())}
        no_global_ids = no_global_ids or set()
        exclude_ranges = exclude_ranges or []
        exclude_ids = exclude_ids or set()
        with click.progressbar(
            diff.associated, label="Update existing clients", show_pos=True
        ) as bar:
            for adguard_device, eero_device in bar:
                if self._is_excluded(eero_device, exclude_ranges, exclude_ids):
                    continue
                use_global = not self._is_no_global(eero_device, no_global_ids)
                new_device = AdGuardClientDevice.from_dhcp_client(
                    eero_device, exclude_ids=conflicting_nicknames, use_global_settings=use_global
                )
                new_device.params = adguard_device.instance.params
                try:
                    self.adguard_client.update_client_device(
                        adguard_device.nickname, new_device
                    )
                except HTTPError as e:
                    click.secho(
                        f"Warning: failed to update '{eero_device.nickname}' "
                        f"[{eero_device.mac_address}]: {e.response.text}",
                        fg="yellow",
                    )

    def delete(
        self,
        diff: DHCPClientTableDiff,
        exclude_ranges: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = None,
        exclude_ids: set[str] = None,
    ):
        exclude_ranges = exclude_ranges or []
        exclude_ids = exclude_ids or set()

        candidates = []
        for device in diff.missing:
            if self._is_excluded(device, exclude_ranges, exclude_ids):
                click.secho(
                    f"Protected from deletion: '{device.nickname}' [{device.mac_address}]",
                    fg="yellow",
                )
            else:
                candidates.append(device)

        if not candidates:
            click.echo("No removed clients found, skipped deletion")
            return
        with click.progressbar(
            candidates, label="Delete removed clients", show_pos=True
        ) as bar:
            for device in bar:
                self.adguard_client.remove_client_device(device.nickname)

    def sync(
        self,
        delete: bool = False,
        overwrite: bool = False,
        exclude_ranges: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = None,
        exclude_ids: set[str] = None,
        no_global_ids: set[str] = None,
    ):  
        exclude_ranges = exclude_ranges or []
        exclude_ids = exclude_ids or set()
        no_global_ids = no_global_ids or set()

        if overwrite:
            # Selectively clear: preserve no-MAC clients (e.g. Docker Network) and
            # any clients that match exclusion rules.
            for client in self.adguard_client.get_clients():
                try:
                    dhcp = client.to_dhcp_client()
                except ValueError:
                    # No MAC — always keep.
                    continue
                if self._is_excluded(dhcp, exclude_ranges, exclude_ids):
                    click.secho(
                        f"Protected from overwrite: '{client.name}'",
                        fg="yellow",
                    )
                    continue
                self.adguard_client.remove_client_device(client.name)

        eero_clients = []
        for client in self.eero_client.get_clients(self.__network):
            try:
                eero_clients.append(client.to_dhcp_client())
            except ValueError:
                click.secho(
                    f"Eero device missing MAC address, skipped device named '{client.nickname}'",
                    fg="red",
                )
        eero_table = DHCPClientTable(eero_clients)

        adguard_clients = []
        for client in self.adguard_client.get_clients():
            try:
                adguard_clients.append(client.to_dhcp_client())
            except ValueError:
                click.secho(
                    f"AdGuard client '{client.name}' has no MAC address — skipped from sync, will not be modified or deleted.",
                    fg="yellow",
                )
        adguard_table = DHCPClientTable(adguard_clients)

        # Pre-build claimed ids from existing adguard clients so new ones don't collide
        claimed_from_adguard: set[str] = set()
        for client in adguard_clients:
            claimed_from_adguard.update(i.lower() for i in client.identifiers)

        dhcp_diff = adguard_table.compare(eero_table)
        if not overwrite:
            self.update(
                dhcp_diff,
                conflicting_nicknames=eero_table.conflicting_nicknames,
                no_global_ids=no_global_ids,
                exclude_ranges=exclude_ranges,
                exclude_ids=exclude_ids,
            )
        self.create(
            dhcp_diff,
            conflicting_nicknames=eero_table.conflicting_nicknames,
            claimed_ids=claimed_from_adguard,
            no_global_ids=no_global_ids,
        )
        if delete:
            self.delete(dhcp_diff, exclude_ranges=exclude_ranges, exclude_ids=exclude_ids)


@click.command()
@click.option(
    "--adguard-host",
    envvar="EAG_ADGUARD_HOST",
    help="AdGuard Home host IP address",
    type=str,
)
@click.option(
    "--adguard-user",
    envvar="EAG_ADGUARD_USER",
    help="AdGuard Home username",
    type=str,
)
@click.option(
    "--adguard-password",
    envvar="EAG_ADGUARD_PASS",
    help="AdGuard Home password",
    type=str,
)
@click.option(
    "--eero-user",
    envvar="EAG_EERO_USER",
    help="Eero email address or phone number",
    type=str,
)
@click.option(
    "--eero-cookie",
    envvar="EAG_EERO_COOKIE",
    help="Eero session cookie",
    type=str,
)
@click.option(
    "--delete",
    "-d",
    envvar="EAG_DELETE",
    is_flag=True,
    default=False,
    help="Delete AdGuard clients not found in Eero DHCP list",
)
@click.option(
    "--confirm",
    "-y",
    envvar="EAG_CONFIRM",
    is_flag=True,
    default=False,
    help="Skip interactive confirmation",
)
@click.option(
    "--overwrite",
    "-o",
    envvar="EAG_OVERWRITE",
    is_flag=True,
    default=False,
    help="Delete all AdGuard clients before sync",
)
@click.option(
    "--exclude-range",
    "-x",
    envvar="EAG_EXCLUDE_RANGE",
    multiple=True,
    help=(
        "CIDR range(s) protected from deletion when --delete is active "
        "(e.g. 192.168.1.0/24). Repeatable. "
        "Env var: comma-separated string."
    ),
)
@click.option(
    "--exclude-id",
    "-e",
    envvar="EAG_EXCLUDE_ID",
    multiple=True,
    help=(
        "Client identifier(s) protected from deletion when --delete is active. "
        "Accepts MAC address, client name, or hostname. Supports wildcards (e.g. my-device*). "
        "Repeatable. "
        "Env var: comma-separated string."
    ),
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Display debug information",
)
@click.option(
    "--no-global-id",
    envvar="EAG_NO_GLOBAL_ID",
    multiple=True,
    help=(
        "Client identifier(s) that are always registered in AdGuard with "
        "'Use global settings' disabled, regardless of eero profile membership. "
        "Accepts MAC address, client name, or hostname. Supports wildcards. "
        "Repeatable. "
        "Env var: comma-separated string."
    ),
)
def sync(
    adguard_host: str = None,
    adguard_user: str = None,
    adguard_password: str = None,
    eero_user: str = None,
    eero_cookie: str = None,
    delete: bool = False,
    confirm: bool = False,
    overwrite: bool = False,
    exclude_range: tuple[str, ...] = (),
    exclude_id: tuple[str, ...] = (),
    debug: bool = False,
    no_global_id: tuple[str, ...] = (),
):
    # Expand comma-separated env var values for multi-options
    exclude_range = _parse_multi_env(exclude_range)
    exclude_id = _parse_multi_env(exclude_id)
    no_global_id = _parse_multi_env(no_global_id)

    # Parse CIDR ranges
    parsed_ranges: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for r in exclude_range:
        try:
            parsed_ranges.append(ipaddress.ip_network(r, strict=False))
        except ValueError:
            raise click.BadParameter(f"Invalid CIDR range: '{r}'", param_hint="--exclude-range")

    # Eero auth
    eero_client = EeroClient(eero_cookie)
    if eero_client.needs_login():
        if not eero_user:
            eero_user = click.prompt("Eero email address or phone number", type=str)
        click.echo("Authenticating Eero...")
        user_token = eero_client.login(eero_user)
        verification_code = click.prompt("Verification code from email or SMS")
        click.echo("Verifying code...")
        eero_client.login_verify(verification_code, user_token)
        click.echo("Eero successfully authenticated")
    else:
        click.echo("Using cached Eero credentials")
    if debug:
        click.echo(f"Eero cookie value: {eero_client.session.cookie}")
        exit()

    # AdGuard auth
    if not adguard_host:
        adguard_host = click.prompt("AdGuard host IP address", type=str)
    adguard_client = AdGuardClient(adguard_host)
    if not adguard_user:
        adguard_user = click.prompt("AdGuard username", type=str)
    if not adguard_password:
        adguard_password = click.prompt("AdGuard password", type=str, hide_input=True)
    adguard_creds = AdGuardCredentialSet(adguard_user, adguard_password)
    click.echo("Authenticating AdGuard...")
    adguard_client.authenticate(adguard_creds)
    click.echo("AdGuard successfully authenticated")

    # Handle
    handler = EeroAdGuardSyncHandler(eero_client, adguard_client)
    if overwrite:
        delete = False
    if not confirm:
        click.confirm("Sync this network?", abort=True)
        if overwrite:
            click.confirm(
                "WARNING: All clients in AdGuard will be deleted, confirm?", abort=True
            )
        if delete:
            click.confirm(
                "WARNING: Clients in AdGuard not found in Eero's DHCP list will be deleted, confirm?",
                abort=True,
            )
    click.echo("Starting sync...")
    start = timer()
    handler.sync(
        delete=delete,
        overwrite=overwrite,
        exclude_ranges=parsed_ranges,
        exclude_ids=set(exclude_id),
        no_global_ids=set(no_global_id) or None,
    )
    elapsed = timer() - start
    click.echo(f"Sync complete in {round(elapsed, 2)}s")
