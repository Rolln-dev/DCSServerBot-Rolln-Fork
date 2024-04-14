import discord
import json
import os
from copy import deepcopy
from core import DCSServerBot, Plugin, PluginRequiredError, Server, Player, TEventListener, PluginInstallationError
from discord.ext import commands
from typing import Optional
from .listener import SlotBlockingListener


class SlotBlocking(Plugin):

    def __init__(self, bot: DCSServerBot, eventlistener: TEventListener):
        super().__init__(bot, eventlistener=eventlistener)
        if not self.locals:
            raise PluginInstallationError(reason=f"No {self.plugin_name}.json file found!", plugin=self.plugin_name)

    def migrate(self, version: str):
        if version != '1.3' or \
                not os.path.exists('config/slotblocking.json') or \
                os.path.exists('config/creditsystem.json'):
            return
        with open('config/slotblocking.json') as file:
            old: dict = json.load(file)
        new = deepcopy(old)
        dirty = False
        for i in range(0, len(old['configs'])):
            # delete stuff from the slotblocking config
            if 'points_per_kill' in old['configs'][i]:
                dirty = True
                del old['configs'][i]['points_per_kill']
            if 'initial_points' in old['configs'][i]:
                dirty = True
                del old['configs'][i]['initial_points']
            # delete stuff from the new creditsystem config
            if 'use_reservations' in new['configs'][i]:
                del new['configs'][i]['use_reservations']
            if 'restricted' in new['configs'][i]:
                del new['configs'][i]['restricted']
        if dirty:
            os.rename('config/slotblocking.json', 'config/slotblocking.bak')
            with open('config/slotblocking.json', 'w') as file:
                json.dump(old, file, indent=2)
            with open('config/creditsystem.json', 'w') as file:
                json.dump(new, file, indent=2)
            self.log.info('  => config/slotblocking.json partly migrated to config/creditsystem.json, please verify!')

    def get_config(self, server: Server, *, use_cache: Optional[bool] = True) -> Optional[dict]:
        if server.name not in self._config or not use_cache:
            default, specific = self.get_base_config(server)
            if default and not specific:
                self._config[server.name] = default
            elif specific and not default:
                self._config[server.name] = specific
            elif default and specific:
                merged = {}
                if 'VIP' in specific:
                    merged['VIP'] = specific['VIP']
                elif 'VIP' in default:
                    merged['VIP'] = default['VIP']
                if 'use_reservations' in specific:
                    merged['use_reservations'] = specific['use_reservations']
                elif 'use_reservations' in default:
                    merged['use_reservations'] = default['use_reservations']
                if 'restricted' in default and 'restricted' not in specific:
                    merged['restricted'] = default['restricted']
                elif 'restricted' not in default and 'restricted' in specific:
                    merged['restricted'] = specific['restricted']
                elif 'restricted' in default and 'restricted' in specific:
                    merged['restricted'] = default['restricted'] + specific['restricted']
                self._config[server.name] = merged
            else:
                return None
        return self._config.get(server.name)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # did a member change its roles?
        if before.roles != after.roles:
            for server in self.bot.servers.values():
                player: Player = server.get_player(discord_id=after.id)
                if not player:
                    ucid = self.bot.get_ucid_by_member(after, verified=True)
                    if not ucid:
                        return
                    roles = [
                        discord.utils.get(self.bot.guilds[0].roles, name=x)
                        for x in self.get_config(server).get('VIP', {}).get('discord', [])
                    ]
                    if not roles:
                        return
                    for role in after.roles:
                        if role in roles:
                            server.sendtoDCS({
                                'command': 'uploadUserRoles',
                                'ucid': ucid,
                                'roles': [x.name for x in after.roles]
                            })
                            break


async def setup(bot: DCSServerBot):
    for plugin in ['mission', 'creditsystem']:
        if plugin not in bot.plugins:
            raise PluginRequiredError(plugin)
    await bot.add_cog(SlotBlocking(bot, SlotBlockingListener))
