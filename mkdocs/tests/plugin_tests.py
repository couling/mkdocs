#!/usr/bin/env python
from __future__ import annotations

import os
import unittest
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from typing_extensions import assert_type
else:

    def assert_type(val, typ):
        return None


from mkdocs import plugins
from mkdocs.commands import build
from mkdocs.config import base
from mkdocs.config import config_options as c
from mkdocs.config.base import ValidationError
from mkdocs.exceptions import Abort, BuildError, PluginError
from mkdocs.tests.base import load_config, tempdir


class _DummyPluginConfig(base.Config):
    foo = c.Type(str, default='default foo')
    bar = c.Type(int, default=0)
    dir = c.Optional(c.Dir(exists=False))


class DummyPlugin(plugins.BasePlugin[_DummyPluginConfig]):
    def on_pre_page(self, content, **kwargs):
        """modify page content by prepending `foo` config value."""
        return f'{self.config.foo} {content}'

    def on_nav(self, item, **kwargs):
        """do nothing (return None) to not modify item."""
        return None

    def on_page_read_source(self, **kwargs):
        """create new source by prepending `foo` config value to 'source'."""
        return f'{self.config.foo} source'

    def on_pre_build(self, **kwargs):
        """do nothing (return None)."""
        return None


class TestPluginClass(unittest.TestCase):
    def test_valid_plugin_options(self) -> None:
        test_dir = 'test'

        options = {
            'foo': 'some value',
            'dir': test_dir,
        }

        cfg_fname = os.path.join('tmp', 'test', 'fname.yml')
        cfg_fname = os.path.abspath(cfg_fname)

        cfg_dirname = os.path.dirname(cfg_fname)
        expected = {
            'foo': 'some value',
            'bar': 0,
            'dir': os.path.join(cfg_dirname, test_dir),
        }

        plugin = DummyPlugin()
        errors, warnings = plugin.load_config(options, config_file_path=cfg_fname)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

        assert_type(plugin.config, _DummyPluginConfig)
        self.assertEqual(plugin.config, expected)

        assert_type(plugin.config.bar, int)
        self.assertEqual(plugin.config.bar, 0)
        assert_type(plugin.config.dir, Optional[str])

    def test_invalid_plugin_options(self):
        plugin = DummyPlugin()
        errors, warnings = plugin.load_config({'foo': 42})
        self.assertEqual(
            errors,
            [('foo', ValidationError("Expected type: <class 'str'> but received: <class 'int'>"))],
        )
        self.assertEqual(warnings, [])

        errors, warnings = plugin.load_config({'bar': 'a string'})
        self.assertEqual(
            errors,
            [('bar', ValidationError("Expected type: <class 'int'> but received: <class 'str'>"))],
        )
        self.assertEqual(warnings, [])

        errors, warnings = plugin.load_config({'invalid_key': 'value'})
        self.assertEqual(errors, [])
        self.assertEqual(
            warnings, [('invalid_key', "Unrecognised configuration name: invalid_key")]
        )


class TestPluginCollection(unittest.TestCase):
    def test_correct_events_registered(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        collection['foo'] = plugin
        self.assertEqual(
            collection.events,
            {
                'startup': [],
                'shutdown': [],
                'serve': [],
                'config': [],
                'pre_build': [plugin.on_pre_build],
                'files': [],
                'nav': [plugin.on_nav],
                'env': [],
                'post_build': [],
                'build_error': [],
                'pre_template': [],
                'template_context': [],
                'post_template': [],
                'pre_page': [plugin.on_pre_page],
                'page_read_source': [plugin.on_page_read_source],
                'page_markdown': [],
                'page_content': [],
                'page_context': [],
                'post_page': [],
            },
        )

    def test_event_priorities(self):
        class PrioPlugin(plugins.BasePlugin):
            config_scheme = base.get_schema(_DummyPluginConfig)

            @plugins.event_priority(100)
            def on_pre_page(self, content, **kwargs):
                pass

            @plugins.event_priority(-100)
            def on_nav(self, item, **kwargs):
                pass

            def on_page_read_source(self, **kwargs):
                pass

            @plugins.event_priority(-50)
            def on_post_build(self, **kwargs):
                pass

        collection = plugins.PluginCollection()
        collection['dummy'] = dummy = DummyPlugin()
        collection['prio'] = prio = PrioPlugin()
        self.assertEqual(
            collection.events['pre_page'],
            [prio.on_pre_page, dummy.on_pre_page],
        )
        self.assertEqual(
            collection.events['nav'],
            [dummy.on_nav, prio.on_nav],
        )
        self.assertEqual(
            collection.events['page_read_source'],
            [dummy.on_page_read_source, prio.on_page_read_source],
        )
        self.assertEqual(
            collection.events['post_build'],
            [prio.on_post_build],
        )

    def test_set_plugin_on_collection(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        collection['foo'] = plugin
        self.assertEqual([(k, v) for k, v in collection.items()], [('foo', plugin)])

    def test_set_multiple_plugins_on_collection(self):
        collection = plugins.PluginCollection()
        plugin1 = DummyPlugin()
        collection['foo'] = plugin1
        plugin2 = DummyPlugin()
        collection['bar'] = plugin2
        self.assertEqual(
            [(k, v) for k, v in collection.items()], [('foo', plugin1), ('bar', plugin2)]
        )

    def test_run_event_on_collection(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        plugin.load_config({'foo': 'new'})
        collection['foo'] = plugin
        self.assertEqual(collection.run_event('pre_page', 'page content'), 'new page content')

    def test_run_event_twice_on_collection(self):
        collection = plugins.PluginCollection()
        plugin1 = DummyPlugin()
        plugin1.load_config({'foo': 'new'})
        collection['foo'] = plugin1
        plugin2 = DummyPlugin()
        plugin2.load_config({'foo': 'second'})
        collection['bar'] = plugin2
        self.assertEqual(
            collection.run_event('pre_page', 'page content'), 'second new page content'
        )

    def test_event_returns_None(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        plugin.load_config({'foo': 'new'})
        collection['foo'] = plugin
        self.assertEqual(collection.run_event('nav', 'nav item'), 'nav item')

    def test_event_empty_item(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        plugin.load_config({'foo': 'new'})
        collection['foo'] = plugin
        self.assertEqual(collection.run_event('page_read_source'), 'new source')

    def test_event_empty_item_returns_None(self):
        collection = plugins.PluginCollection()
        plugin = DummyPlugin()
        plugin.load_config({'foo': 'new'})
        collection['foo'] = plugin
        self.assertEqual(collection.run_event('pre_build'), None)

    def test_run_undefined_event_on_collection(self):
        collection = plugins.PluginCollection()
        self.assertEqual(collection.run_event('pre_page', 'page content'), 'page content')

    def test_run_unknown_event_on_collection(self):
        collection = plugins.PluginCollection()
        with self.assertRaises(KeyError):
            collection.run_event('unknown', 'page content')

    @tempdir()
    def test_run_build_error_event(self, site_dir):
        build_errors = []

        class PluginRaisingError(plugins.BasePlugin):
            def __init__(self, error_on):
                self.error_on = error_on

            def on_pre_page(self, page, **kwargs):
                if self.error_on == 'pre_page':
                    raise BuildError('pre page error')
                return page

            def on_page_markdown(self, markdown, **kwargs):
                if self.error_on == 'page_markdown':
                    raise BuildError('page markdown error')
                return markdown

            def on_page_content(self, html, **kwargs):
                if self.error_on == 'page_content':
                    raise PluginError('page content error')
                return html

            def on_post_page(self, html, **kwargs):
                if self.error_on == 'post_page':
                    raise ValueError('post page error')

            def on_build_error(self, error, **kwargs):
                build_errors.append(error)

        cfg = load_config(site_dir=site_dir)
        cfg.plugins['errorplugin'] = PluginRaisingError(error_on='pre_page')
        with self.assertLogs('mkdocs', level='ERROR'):
            self.assertRaises(Abort, build.build, cfg)

        cfg = load_config(site_dir=site_dir)
        cfg.plugins['errorplugin'] = PluginRaisingError(error_on='page_markdown')
        with self.assertLogs('mkdocs', level='ERROR'):
            self.assertRaises(Abort, build.build, cfg)

        cfg = load_config(site_dir=site_dir)
        cfg.plugins['errorplugin'] = PluginRaisingError(error_on='page_content')
        with self.assertLogs('mkdocs', level='ERROR'):
            self.assertRaises(Abort, build.build, cfg)

        cfg = load_config(site_dir=site_dir)
        cfg.plugins['errorplugin'] = PluginRaisingError(error_on='post_page')
        with self.assertLogs('mkdocs', level='ERROR'):
            self.assertRaises(ValueError, build.build, cfg)

        cfg = load_config(site_dir=site_dir)
        cfg.plugins['errorplugin'] = PluginRaisingError(error_on='')
        build.build(cfg)

        self.assertEqual(len(build_errors), 4)
        self.assertIs(build_errors[0].__class__, BuildError)
        self.assertEqual(str(build_errors[0]), 'pre page error')
        self.assertIs(build_errors[1].__class__, BuildError)
        self.assertEqual(str(build_errors[1]), 'page markdown error')
        self.assertIs(build_errors[2].__class__, PluginError)
        self.assertEqual(str(build_errors[2]), 'page content error')
        self.assertIs(build_errors[3].__class__, ValueError)
        self.assertEqual(str(build_errors[3]), 'post page error')
