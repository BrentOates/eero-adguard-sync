import ipaddress
import logging
import re
from typing import Union
from dataclasses import dataclass, field

import macaddress

logger = logging.getLogger(__name__)


@dataclass
class DHCPClient:
    mac_address: macaddress.MAC
    ip_interfaces: list[Union[ipaddress.IPv4Interface, ipaddress.IPv6Interface]]
    nickname: str
    hostname: str
    instance: object
    tags: list[str] = field(default_factory=list)

    @property
    def simplified_nickname(self) -> str:
        return re.sub('[^0-9a-zA-Z ]+', '', self.nickname).replace(' ', '-')

    @property
    def identifiers(self) -> set[str]:
        identifiers = {str(self.mac_address)}
        nick_or_host = self.simplified_nickname or self.hostname
        if nick_or_host:
            identifiers.add(nick_or_host)
        for interface in self.ip_interfaces:
            # Use compressed form only — exploded IPv6 is a different string for
            # the same address and AdGuard normalises internally, causing conflicts.
            identifiers.add(interface.ip.compressed)
        return identifiers


@dataclass
class DHCPClientTableDiff:
    discovered: list[DHCPClient]
    associated: list[tuple[DHCPClient, DHCPClient]]
    missing: list[DHCPClient]


@dataclass
class DHCPClientTable:
    clients: list[DHCPClient]

    def __post_init__(self):
        self.clients = self._merge_duplicate_macs(self.clients)

    def _merge_duplicate_macs(self, clients: list[DHCPClient]) -> list[DHCPClient]:
        seen: dict[str, DHCPClient] = {}
        for client in clients:
            mac = str(client.mac_address)
            if mac in seen:
                existing = seen[mac]
                ip_map = {str(i.ip): i for i in existing.ip_interfaces}
                for iface in client.ip_interfaces:
                    ip_map.setdefault(str(iface.ip), iface)
                nickname = (
                    client.nickname
                    if len(client.nickname) > len(existing.nickname)
                    else existing.nickname
                )
                seen[mac] = DHCPClient(
                    mac_address=existing.mac_address,
                    ip_interfaces=list(ip_map.values()),
                    nickname=nickname,
                    hostname=existing.hostname,
                    instance=existing.instance,
                    tags=list(set(existing.tags) | set(client.tags)),
                )
                logger.warning(
                    "Merged duplicate MAC entries: '%s' + '%s' -> '%s'",
                    existing.nickname,
                    client.nickname,
                    seen[mac].nickname,
                )
            else:
                seen[mac] = client
        return list(seen.values())

    @property
    def conflicting_nicknames(self) -> set[str]:
        """Simplified nicknames that appear in more than one client in this table."""
        counts: dict[str, int] = {}
        for client in self.clients:
            nick = client.simplified_nickname
            if nick:
                counts[nick] = counts.get(nick, 0) + 1
        return {nick for nick, count in counts.items() if count > 1}

    @property
    def hash_table(self) -> dict[str, DHCPClient]:
        return {str(i.mac_address): i for i in self.clients}

    @property
    def nickname_table(self) -> dict[str, DHCPClient]:
        """Index by simplified nickname; only includes unambiguous (unique) entries."""
        counts: dict[str, int] = {}
        for client in self.clients:
            nick = client.simplified_nickname
            if nick:
                counts[nick] = counts.get(nick, 0) + 1
        return {
            client.simplified_nickname: client
            for client in self.clients
            if client.simplified_nickname and counts.get(client.simplified_nickname, 0) == 1
        }

    def __discover(self, table: "DHCPClientTable") -> list[DHCPClient]:
        tbl = self.hash_table
        return [v for k, v in table.hash_table.items() if k not in tbl]

    def __associate(
        self, table: "DHCPClientTable"
    ) -> list[tuple[DHCPClient, DHCPClient]]:
        tbl = table.hash_table
        return [(v, tbl[k]) for k, v in self.hash_table.items() if k in tbl]

    def __prune(self, table: "DHCPClientTable") -> list[DHCPClient]:
        tbl = table.hash_table
        return [v for k, v in self.hash_table.items() if k not in tbl]

    def compare(self, table: "DHCPClientTable") -> DHCPClientTableDiff:
        # Primary pass: match by MAC address
        mac_associated = self.__associate(table)
        mac_discovered = self.__discover(table)   # in eero, not in adguard by MAC
        mac_missing = self.__prune(table)          # in adguard, not in eero by MAC

        # Nickname fallback: for each unmatched eero client (mac_discovered), check
        # if there is exactly one unmatched adguard client (mac_missing) with the same
        # simplified nickname. If so, treat as an update (MAC rotation scenario).
        adguard_missing_by_nick: dict[str, DHCPClient] = {}
        for client in mac_missing:
            nick = client.simplified_nickname
            if nick:
                # Mark ambiguous with None so we don't false-match
                adguard_missing_by_nick[nick] = (
                    None if nick in adguard_missing_by_nick else client
                )

        nickname_matched_adguard: set[str] = set()
        extra_associated: list[tuple[DHCPClient, DHCPClient]] = []
        still_discovered: list[DHCPClient] = []

        for eero_client in mac_discovered:
            nick = eero_client.simplified_nickname
            adguard_match = adguard_missing_by_nick.get(nick) if nick else None
            if adguard_match is not None:
                extra_associated.append((adguard_match, eero_client))
                nickname_matched_adguard.add(nick)
                logger.info(
                    "Matched '%s' by nickname after MAC change (old: %s -> new: %s)",
                    eero_client.nickname,
                    adguard_match.mac_address,
                    eero_client.mac_address,
                )
            else:
                still_discovered.append(eero_client)

        still_missing = [
            c for c in mac_missing
            if c.simplified_nickname not in nickname_matched_adguard
        ]

        return DHCPClientTableDiff(
            discovered=still_discovered,
            associated=mac_associated + extra_associated,
            missing=still_missing,
        )
