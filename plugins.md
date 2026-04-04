16.1. Structuring Python Plugins — QGIS Documentation documentation              

This documentation is for a QGIS version which has reached end of life. Instead visit the [latest version](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html).

[QGIS Documentation ![Logo](../../../_static/logo.png)](../../index.html) 

3.40

  

[Index](../../../genindex.html)

About QGIS

- [Preamble](../../about/preamble.html)
- [Foreword](../../about/foreword.html)
- [Conventions](../../about/conventions.html)
- [Features](../../about/features.html)
- [Help and Support](../../about/help_and_support.html)
- [Contributors](../../about/contributors.html)
- [Complying with Licenses](../../about/license/index.html)

For Users

- [QGIS Desktop User Guide/Manual (QGIS 3.40)](../../user_manual/index.html)
- [QGIS Server Guide/Manual (QGIS 3.40)](../../server_manual/index.html)
- [Training Manual](../../training_manual/index.html)
- [A Gentle Introduction to GIS](../../gentle_gis_introduction/index.html)

For Writers

- [Documentation Guidelines](../../documentation_guidelines/index.html)

For Developers

- [PyQGIS Cookbook (QGIS 3.40)](../index.html)
  - [1\. Introduction](../intro.html)
  - [2\. Loading Projects](../loadproject.html)
  - [3\. Loading Layers](../loadlayer.html)
  - [4\. Accessing the Table Of Contents (TOC)](../legend.html)
  - [5\. Using Raster Layers](../raster.html)
  - [6\. Using Vector Layers](../vector.html)
  - [7\. Geometry Handling](../geometry.html)
  - [8\. Projections Support](../crs.html)
  - [9\. Using the Map Canvas](../canvas.html)
  - [10\. Map Rendering and Printing](../composer.html)
  - [11\. Expressions, Filtering and Calculating Values](../expressions.html)
  - [12\. Reading And Storing Settings](../settings.html)
  - [13\. Communicating with the user](../communicating.html)
  - [14\. Authentication infrastructure](../authentication.html)
  - [15\. Tasks - doing heavy work in the background](../tasks.html)
  - [16\. Developing Python Plugins](index.html)
    - [16.1. Structuring Python Plugins](#)
      - [16.1.1. Getting started](#getting-started)
      - [16.1.2. Writing plugin code](#writing-plugin-code)
      - [16.1.3. Documenting plugins](#documenting-plugins)
      - [16.1.4. Translating plugins](#translating-plugins)
      - [16.1.5. Sharing your plugin](#sharing-your-plugin)
      - [16.1.6. Tips and Tricks](#tips-and-tricks)
    - [16.2. Code Snippets](snippets.html)
    - [16.3. IDE settings for writing and debugging plugins](ide_debugging.html)
    - [16.4. Releasing your plugin](releasing.html)
  - [17\. Writing a Processing plugin](../processing.html)
  - [18\. Using Plugin Layers](../pluginlayer.html)
  - [19\. Network analysis library](../network_analysis.html)
  - [20\. QGIS Server and Python](../server.html)
  - [21\. Cheat sheet for PyQGIS](../cheat_sheet.html)
- [Developers Guide](../../developers_guide/index.html)

[QGIS Documentation](../../index.html)

- [](../../index.html)
- [PyQGIS Developer Cookbook](../index.html)
- [16\. Developing Python Plugins](index.html)
- 16.1. Structuring Python Plugins
- - [View page source](../../../_sources/docs/pyqgis_developer_cookbook/plugins/plugins.rst.txt)
  
  [Learn how to contribute!](https://qgis.org/community/involve/)

[Previous](index.html "16. Developing Python Plugins") [Next](snippets.html "16.2. Code Snippets")

* * *

# 16.1. Structuring Python Plugins[](#structuring-python-plugins "Link to this heading")

- [Getting started](#getting-started)
  
  - [Set up plugin file structure](#set-up-plugin-file-structure)
    
- [Writing plugin code](#writing-plugin-code)
  
  - [metadata.txt](#metadata-txt)
    
  - [\_\_init\_\_.py](#init-py)
    
  - [mainPlugin.py](#mainplugin-py)
    
- [Documenting plugins](#documenting-plugins)
  
- [Translating plugins](#translating-plugins)
  
  - [Software requirements](#software-requirements)
    
  - [Files and directory](#files-and-directory)
    
    - [.pro file](#pro-file)
      
    - [.ts file](#ts-file)
      
    - [.qm file](#qm-file)
      
  - [Translate using Makefile](#translate-using-makefile)
    
  - [Load the plugin](#load-the-plugin)
    
- [Sharing your plugin](#sharing-your-plugin)
  
- [Tips and Tricks](#tips-and-tricks)
  
  - [Plugin Reloader](#plugin-reloader)
    
  - [Automate packaging, release and translation with qgis-plugin-ci](#automate-packaging-release-and-translation-with-qgis-plugin-ci)
    
  - [Accessing Plugins](#accessing-plugins)
    
  - [Log Messages](#log-messages)
    
  - [Resource File](#resource-file)
    

The main steps for creating a plugin are:

1. _Idea_: Have an idea about what you want to do with your new QGIS plugin.
  
2. _Setup_: [Create the files for your plugin](#plugin-setup). Depending on the plugin type, some are mandatory while others are optional
  
3. _Develop_: [Write the code](#plugin-development) in appropriate files
  
4. _Document_: [Write the plugin documentation](#plugin-docs)
  
5. Optionally: _Translate_: [Translate your plugin](#plugin-translation) into different languages
  
6. _Test_: [Reload your plugin](#plugin-reloader-trick) to check if everything is OK
  
7. _Publish_: Publish your plugin in QGIS repository or make your own repository as an “arsenal” of personal “GIS weapons”.
  

## [16.1.1. Getting started](#id1)[](#getting-started "Link to this heading")

Before starting to write a new plugin, have a look at the [Official Python plugin repository](releasing.html#official-pyqgis-repository). The source code of existing plugins can help you to learn more about programming. You may also find that a similar plugin already exists and you may be able to extend it or at least build on it to develop your own.

### [16.1.1.1. Set up plugin file structure](#id2)[](#set-up-plugin-file-structure "Link to this heading")

To get started with a new plugin, we need to set up the necessary plugin files.

There are two plugin template resources that can help get you started:

- For educational purposes or whenever a minimalist approach is desired, the [minimal plugin template](https://github.com/wonder-sk/qgis-minimal-plugin) provides the basic files (skeleton) necessary to create a valid QGIS Python plugin.
  
- For a more fully feature plugin template, the [Plugin Builder](https://plugins.qgis.org/plugins/pluginbuilder3/) can create templates for multiple different plugin types, including features such as localization (translation) and testing.
  

A typical plugin directory includes the following files:

- `metadata.txt` - _required_ - Contains general info, version, name and some other metadata used by plugins website and plugin infrastructure.
  
- `__init__.py` - _required_ - The starting point of the plugin. It has to have the `classFactory()` method and may have any other initialisation code.
  
- `mainPlugin.py` - _core code_ - The main working code of the plugin. Contains all the information about the actions of the plugin and the main code.
  
- `form.ui` - _for plugins with custom GUI_ - The GUI created by Qt Designer.
  
- `form.py` - _compiled GUI_ - The translation of the form.ui described above to Python.
  
- `resources.qrc` - _optional_ - An .xml document created by Qt Designer. Contains relative paths to resources used in the GUI forms.
  
- `resources.py` - _compiled resources, optional_ - The translation of the .qrc file described above to Python.
  
- `LICENSE` - _required_ if plugin is to be published or updated in the QGIS Plugins Directory, otherwise _optional_. File should be a plain text file with no file extension in the filename.
  

Warning

If you plan to upload the plugin to the [Official Python plugin repository](releasing.html#official-pyqgis-repository) you must check that your plugin follows some additional rules, required for plugin [Validation](releasing.html#official-pyqgis-repository-validation).

## [16.1.2. Writing plugin code](#id3)[](#writing-plugin-code "Link to this heading")

The following section shows what content should be added in each of the files introduced above.

### [16.1.2.1. metadata.txt](#id4)[](#metadata-txt "Link to this heading")

First, the Plugin Manager needs to retrieve some basic information about the plugin such as its name, description etc. This information is stored in `metadata.txt`.

Note

All metadata must be in UTF-8 encoding.

| 
Metadata name

 | Required | Notes |
| --- | --- | --- |
| name | True | a short string containing the name of the plugin |
| qgisMinimumVersion | True | dotted notation of minimum QGIS version |
| qgisMaximumVersion | False | dotted notation of maximum QGIS version |
| description | True | short text which describes the plugin, no HTML allowed |
| about | True | longer text which describes the plugin in details, no HTML allowed |
| version | True | short string with the version dotted notation |
| author | True | author name |
| email | True | email of the author, only shown on the website to logged in users, but visible in the Plugin Manager after the plugin is installed |
| changelog | False | string, can be multiline, no HTML allowed |
| experimental | False | boolean flag, `True` or `False` - `True` if this version is experimental |
| deprecated | False | boolean flag, `True` or `False`, applies to the whole plugin and not just to the uploaded version |
| tags | False | comma separated list, spaces are allowed inside individual tags |
| homepage | False | a valid URL pointing to the homepage of your plugin |
| repository | True | a valid URL for the source code repository |
| tracker | False | a valid URL for tickets and bug reports |
| icon | False | a file name or a relative path (relative to the base folder of the plugin’s compressed package) of a web friendly image (PNG, JPEG) |
| category | False | one of `Raster`, `Vector`, `Database`, `Mesh` and `Web` |
| plugin\_dependencies | False | PIP-like comma separated list of other plugins to install, use plugin names coming from their metadata’s name field |
| server | False | boolean flag, `True` or `False`, determines if the plugin has a server interface |
| hasProcessingProvider | False | boolean flag, `True` or `False`, determines if the plugin provides processing algorithms |

By default, plugins are placed in the Plugins menu (we will see in the next section how to add a menu entry for your plugin) but they can also be placed into Raster, Vector, Database, Mesh and Web menus.

A corresponding “category” metadata entry exists to specify that, so the plugin can be classified accordingly. This metadata entry is used as tip for users and tells them where (in which menu) the plugin can be found. Allowed values for “category” are: Vector, Raster, Database or Web. For example, if your plugin will be available from Raster menu, add this to `metadata.txt`

category\=Raster

Note

If qgisMaximumVersion is empty, it will be automatically set to the major version plus .99 when uploaded to the [Official Python plugin repository](releasing.html#official-pyqgis-repository).

An example for this metadata.txt

; the next section is mandatory

\[general\]
name\=HelloWorld
email\=me@example.com
author\=Just Me
qgisMinimumVersion\=3.0
description\=This is an example plugin for greeting the world.
    Multiline is allowed:
    lines starting with spaces belong to the same
    field, in this case to the "description" field.
    HTML formatting is not allowed.
about\=This paragraph can contain a detailed description
    of the plugin. Multiline is allowed, HTML is not.
version\=version 1.2
tracker\=http://bugs.itopen.it
repository\=http://www.itopen.it/repo
; end of mandatory metadata

; start of optional metadata
category\=Raster
changelog\=The changelog lists the plugin versions
    and their changes as in the example below:
    1.0 \- First stable release
    0.9 \- All features implemented
    0.8 \- First testing release

; Tags are in comma separated value format, spaces are allowed within the
; tag name.
; Tags should be in English language. Please also check for existing tags and
; synonyms before creating a new one.
tags\=wkt,raster,hello world

; these metadata can be empty, they will eventually become mandatory.
homepage\=https://www.itopen.it
icon\=icon.png

; experimental flag (applies to the single version)
experimental\=True

; deprecated flag (applies to the whole plugin and not only to the uploaded version)
deprecated\=False

; if empty, it will be automatically set to major version + .99
qgisMaximumVersion\=3.99

; Since QGIS 3.8, a comma separated list of plugins to be installed
; (or upgraded) can be specified.
; The example below will try to install (or upgrade) "MyOtherPlugin" version 1.12
; and any version of "YetAnotherPlugin".
; Both "MyOtherPlugin" and "YetAnotherPlugin" names come from their own metadata's
; name field
plugin\_dependencies\=MyOtherPlugin\==1.12,YetAnotherPlugin

### [16.1.2.2. \_\_init\_\_.py](#id5)[](#init-py "Link to this heading")

This file is required by Python’s import system. Also, QGIS requires that this file contains a `classFactory()` function, which is called when the plugin gets loaded into QGIS. It receives a reference to the instance of [`QgisInterface`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface "(in QGIS Python API v3.40)") and must return an object of your plugin’s class from the `mainplugin.py` — in our case it’s called `TestPlugin` (see below). This is how `__init__.py` should look like

def classFactory(iface):
  from .mainPlugin import TestPlugin
  return TestPlugin(iface)

\# any other initialisation needed

### [16.1.2.3. mainPlugin.py](#id6)[](#mainplugin-py "Link to this heading")

This is where the magic happens and this is how magic looks like: (e.g. `mainPlugin.py`)

from qgis.PyQt.QtGui import \*
from qgis.PyQt.QtWidgets import \*

\# initialize Qt resources from file resources.py
from . import resources

class TestPlugin:

  def \_\_init\_\_(self, iface):
    \# save reference to the QGIS interface
    self.iface \= iface

  def initGui(self):
    \# create action that will start plugin configuration
    self.action \= QAction(QIcon("testplug:icon.png"),
                          "Test plugin",
                          self.iface.mainWindow())
    self.action.setObjectName("testAction")
    self.action.setWhatsThis("Configuration for test plugin")
    self.action.setStatusTip("This is status tip")
    self.action.triggered.connect(self.run)

    \# add toolbar button and menu item
    self.iface.addToolBarIcon(self.action)
    self.iface.addPluginToMenu("&Test plugins", self.action)

    \# connect to signal renderComplete which is emitted when canvas
    \# rendering is done
    self.iface.mapCanvas().renderComplete.connect(self.renderTest)

  def unload(self):
    \# remove the plugin menu item and icon
    self.iface.removePluginMenu("&Test plugins", self.action)
    self.iface.removeToolBarIcon(self.action)

    \# disconnect form signal of the canvas
    self.iface.mapCanvas().renderComplete.disconnect(self.renderTest)

  def run(self):
    \# create and show a configuration dialog or something similar
    print("TestPlugin: run called!")

  def renderTest(self, painter):
    \# use painter for drawing to map canvas
    print("TestPlugin: renderTest called!")

The only plugin functions that must exist in the main plugin source file (e.g. `mainPlugin.py`) are:

- `__init__` which gives access to QGIS interface
  
- `initGui()` called when the plugin is loaded
  
- `unload()` called when the plugin is unloaded
  

In the above example, [`addPluginToMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToMenu "(in QGIS Python API v3.40)") is used. This will add the corresponding menu action to the Plugins menu. Alternative methods exist to add the action to a different menu. Here is a list of those methods:

- [`addPluginToRasterMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToRasterMenu "(in QGIS Python API v3.40)")
  
- [`addPluginToVectorMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToVectorMenu "(in QGIS Python API v3.40)")
  
- [`addPluginToDatabaseMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToDatabaseMenu "(in QGIS Python API v3.40)")
  
- [`addPluginToWebMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToWebMenu "(in QGIS Python API v3.40)")
  

All of them have the same syntax as the [`addPluginToMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.addPluginToMenu "(in QGIS Python API v3.40)") method.

Adding your plugin menu to one of those predefined method is recommended to keep consistency in how plugin entries are organized. However, you can add your custom menu group directly to the menu bar, as the next example demonstrates:

def initGui(self):
    self.menu \= QMenu(self.iface.mainWindow())
    self.menu.setObjectName("testMenu")
    self.menu.setTitle("MyMenu")

    self.action \= QAction(QIcon("testplug:icon.png"),
                          "Test plugin",
                          self.iface.mainWindow())
    self.action.setObjectName("testAction")
    self.action.setWhatsThis("Configuration for test plugin")
    self.action.setStatusTip("This is status tip")
    self.action.triggered.connect(self.run)
    self.menu.addAction(self.action)

    menuBar \= self.iface.mainWindow().menuBar()
    menuBar.insertMenu(self.iface.firstRightStandardMenu().menuAction(),
                       self.menu)

def unload(self):
    self.menu.deleteLater()

Don’t forget to set `QAction` and `QMenu` `objectName` to a name specific to your plugin so that it can be customized.

While help and about actions can also be added to your custom menu, a convenient place to make them available is in the QGIS main Help ► Plugins menu. This is done using the [`pluginHelpMenu()`](https://qgis.org/pyqgis/3.40/gui/QgisInterface.html#qgis.gui.QgisInterface.pluginHelpMenu "(in QGIS Python API v3.40)") method.

def initGui(self):

    self.help\_action \= QAction(
        QIcon("testplug:icon.png"),
        self.tr("Test Plugin..."),
        self.iface.mainWindow()
    )
    \# Add the action to the Help menu
    self.iface.pluginHelpMenu().addAction(self.help\_action)

    self.help\_action.triggered.connect(self.show\_help)

@staticmethod
def show\_help():
    """ Open the online help. """
    QDesktopServices.openUrl(QUrl('https://docs.qgis.org'))

def unload(self):

    self.iface.pluginHelpMenu().removeAction(self.help\_action)
    del self.help\_action

When working on a real plugin it’s wise to write the plugin in another (working) directory and create a makefile which will generate UI + resource files and install the plugin into your QGIS installation.

## [16.1.3. Documenting plugins](#id7)[](#documenting-plugins "Link to this heading")

The documentation for the plugin can be written as HTML help files. The `qgis.utils` module provides a function, `showPluginHelp()` which will open the help file browser, in the same way as other QGIS help.

The `showPluginHelp()` function looks for help files in the same directory as the calling module. It will look for, in turn, `index-ll_cc.html`, `index-ll.html`, `index-en.html`, `index-en_us.html` and `index.html`, displaying whichever it finds first. Here `ll_cc` is the QGIS locale. This allows multiple translations of the documentation to be included with the plugin.

The `showPluginHelp()` function can also take parameters packageName, which identifies a specific plugin for which the help will be displayed, filename, which can replace “index” in the names of files being searched, and section, which is the name of an html anchor tag in the document on which the browser will be positioned.

## [16.1.4. Translating plugins](#id8)[](#translating-plugins "Link to this heading")

With a few steps you can set up the environment for the plugin localization so that depending on the locale settings of your computer the plugin will be loaded in different languages.

### [16.1.4.1. Software requirements](#id9)[](#software-requirements "Link to this heading")

The easiest way to create and manage all the translation files is to install [Qt Linguist](https://doc.qt.io/archives/qt-5.15/qtlinguist-index.html). In a Debian-based GNU/Linux environment you can install it typing:

sudo apt install qttools5\-dev\-tools

### [16.1.4.2. Files and directory](#id10)[](#files-and-directory "Link to this heading")

When you create the plugin you will find the `i18n` folder within the main plugin directory.

**All the translation files have to be within this directory.**

#### [16.1.4.2.1. .pro file](#id11)[](#pro-file "Link to this heading")

First you should create a `.pro` file, that is a _project_ file that can be managed by **Qt Linguist**.

In this `.pro` file you have to specify all the files and forms you want to translate. This file is used to set up the localization files and variables. A possible project file, matching the structure of our [example plugin](#plugin-files-architecture):

FORMS \= ../form.ui
SOURCES \= ../your\_plugin.py
TRANSLATIONS \= your\_plugin\_it.ts

Your plugin might follow a more complex structure, and it might be distributed across several files. If this is the case, keep in mind that `pylupdate5`, the program we use to read the `.pro` file and update the translatable string, does not expand wild card characters, so you need to place every file explicitly in the `.pro` file. Your project file might then look like something like this:

FORMS \= ../ui/about.ui ../ui/feedback.ui \\
        ../ui/main\_dialog.ui
SOURCES \= ../your\_plugin.py ../computation.py \\
          ../utils.py

Furthermore, the `your_plugin.py` file is the file that _calls_ all the menu and sub-menus of your plugin in the QGIS toolbar and you want to translate them all.

Finally with the _TRANSLATIONS_ variable you can specify the translation languages you want.

Warning

Be sure to name the `ts` file like `your_plugin_` + `language` + `.ts` otherwise the language loading will fail! Use the 2 letter shortcut for the language (**it** for Italian, **de** for German, etc…)

#### [16.1.4.2.2. .ts file](#id12)[](#ts-file "Link to this heading")

Once you have created the `.pro` you are ready to generate the `.ts` file(s) for the language(s) of your plugin.

Open a terminal, go to `your_plugin/i18n` directory and type:

pylupdate5 your\_plugin.pro

you should see the `your_plugin_language.ts` file(s).

Open the `.ts` file with **Qt Linguist** and start to translate.

#### [16.1.4.2.3. .qm file](#id13)[](#qm-file "Link to this heading")

When you finish to translate your plugin (if some strings are not completed the source language for those strings will be used) you have to create the `.qm` file (the compiled `.ts` file that will be used by QGIS).

Just open a terminal cd in `your_plugin/i18n` directory and type:

lrelease your\_plugin.ts

now, in the `i18n` directory you will see the `your_plugin.qm` file(s).

### [16.1.4.3. Translate using Makefile](#id14)[](#translate-using-makefile "Link to this heading")

Alternatively you can use the makefile to extract messages from python code and Qt dialogs, if you created your plugin with Plugin Builder. At the beginning of the Makefile there is a LOCALES variable:

LOCALES \= en

Add the abbreviation of the language to this variable, for example for Hungarian language:

LOCALES \= en hu

Now you can generate or update the `hu.ts` file (and the `en.ts` too) from the sources by:

make transup

After this, you have updated `.ts` file for all languages set in the LOCALES variable. Use **Qt Linguist** to translate the program messages. Finishing the translation the `.qm` files can be created by the transcompile:

make transcompile

You have to distribute `.ts` files with your plugin.

### [16.1.4.4. Load the plugin](#id15)[](#load-the-plugin "Link to this heading")

In order to see the translation of your plugin, open QGIS, change the language (Settings ► Options ► General) and restart QGIS.

You should see your plugin in the correct language.

Warning

If you change something in your plugin (new UIs, new menu, etc..) you have to **generate again** the update version of both `.ts` and `.qm` file, so run again the command of above.

## [16.1.5. Sharing your plugin](#id16)[](#sharing-your-plugin "Link to this heading")

QGIS is hosting hundreds of plugins in the plugin repository. Consider sharing yours! It will extend the possibilities of QGIS and people will be able to learn from your code. All hosted plugins can be found and installed from within QGIS with the Plugin Manager.

Information and requirements are here: [plugins.qgis.org](https://plugins.qgis.org/).

## [16.1.6. Tips and Tricks](#id17)[](#tips-and-tricks "Link to this heading")

### [16.1.6.1. Plugin Reloader](#id18)[](#plugin-reloader "Link to this heading")

During development of your plugin you will frequently need to reload it in QGIS for testing. This is very easy using the **Plugin Reloader** plugin. You can find it with the [Plugin Manager](../../user_manual/plugins/plugins.html#plugins).

### [16.1.6.2. Automate packaging, release and translation with qgis-plugin-ci](#id19)[](#automate-packaging-release-and-translation-with-qgis-plugin-ci "Link to this heading")

[qgis-plugin-ci](https://opengisch.github.io/qgis-plugin-ci/) provides a command line interface to perform automated packaging and deployment for QGIS plugins on your computer, or using continuous integration like [GitHub workflows](https://docs.github.com/en/actions/how-tos/write-workflows) or [Gitlab-CI](https://docs.gitlab.com/ci/) as well as [Transifex](https://www.transifex.com) for translation.

It allows releasing, translating, publishing or generating an XML plugin repository file via CLI or in CI actions.

### [16.1.6.3. Accessing Plugins](#id20)[](#accessing-plugins "Link to this heading")

You can access all the classes of installed plugins from within QGIS using python, which can be handy for debugging purposes.

my\_plugin \= qgis.utils.plugins\['My Plugin'\]

### [16.1.6.4. Log Messages](#id21)[](#log-messages "Link to this heading")

Plugins have their own tab within the [Log Messages Panel](../../user_manual/introduction/general_tools.html#log-message-panel).

### [16.1.6.5. Resource File](#id22)[](#resource-file "Link to this heading")

Some plugins use resource files, for example `resources.qrc` which define resources for the GUI, such as icons:

<RCC>
  <qresource prefix="/plugins/testplug" \>
     <file>icon.png</file>
  </qresource>
</RCC>

It is good to use a prefix that will not collide with other plugins or any parts of QGIS, otherwise you might get resources you did not want. Now you just need to generate a Python file that will contain the resources. It’s done with **pyrcc5** command:

pyrcc5 \-o resources.py resources.qrc

Note

In Windows environments, attempting to run the **pyrcc5** from Command Prompt or Powershell will probably result in the error “Windows cannot access the specified device, path, or file \[…\]”. The easiest solution is probably to use the OSGeo4W Shell but if you are comfortable modifying the PATH environment variable or specifiying the path to the executable explicitly you should be able to find it at `<Your QGIS Install Directory>\bin\pyrcc5.exe`.

[Previous](index.html "16. Developing Python Plugins") [Next](snippets.html "16.2. Code Snippets")

* * *

© Copyright 2002-now, QGIS project. Last updated on 2026 Mar 16, 15:45 +0000.

Built with [Sphinx](https://www.sphinx-doc.org/) using a [theme](https://github.com/readthedocs/sphinx_rtd_theme) provided by [Read the Docs](https://readthedocs.org).

QGIS Documentation v: 3.40

Languages

[en](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[cs](https://docs.qgis.org/3.40/cs/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[de](https://docs.qgis.org/3.40/de/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[es](https://docs.qgis.org/3.40/es/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[fr](https://docs.qgis.org/3.40/fr/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[hu](https://docs.qgis.org/3.40/hu/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[it](https://docs.qgis.org/3.40/it/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[ja](https://docs.qgis.org/3.40/ja/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[ko](https://docs.qgis.org/3.40/ko/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[lt](https://docs.qgis.org/3.40/lt/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[nl](https://docs.qgis.org/3.40/nl/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[pl](https://docs.qgis.org/3.40/pl/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[pt\_BR](https://docs.qgis.org/3.40/pt_BR/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[pt\_PT](https://docs.qgis.org/3.40/pt_PT/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[ro](https://docs.qgis.org/3.40/ro/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[ru](https://docs.qgis.org/3.40/ru/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[sv](https://docs.qgis.org/3.40/sv/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[zh-Hans](https://docs.qgis.org/3.40/zh-Hans/docs/pyqgis_developer_cookbook/plugins/plugins.html)

Versions

[testing](https://docs.qgis.org/testing/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[latest](https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.44](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.40](https://docs.qgis.org/3.40/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.34](https://docs.qgis.org/3.34/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.28](https://docs.qgis.org/3.28/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.22](https://docs.qgis.org/3.22/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.16](https://docs.qgis.org/3.16/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.10](https://docs.qgis.org/3.10/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[3.4](https://docs.qgis.org/3.4/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

[2.18](https://docs.qgis.org/2.18/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)

Downloads

[PDF](https://docs.qgis.org/3.40/pdf)

[HTML](https://docs.qgis.org/3.40/zip)

On QGIS Project

[Home](https://qgis.org)

[C++ API](https://qgis.org/api/3.40)

[PyQGIS API](https://qgis.org/pyqgis/3.40)

[Source](https://github.com/qgis/QGIS/tree/release-3_40)