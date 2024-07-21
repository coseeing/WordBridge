import gui
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsDialog
import wx
import addonHandler
import csv
import os


addonHandler.initTranslation()

GUIDELINE_TEXT = _(
"""Guideline:
Users can add words to improve the accuracy of added terms. It is recommended to add specialized terms that may not be present in the model's training data or terms that the model frequently make mistakes. The zhuyin or pinyin of an added word is optional, but providing it can help improve correctness. 

For the format of pinyin and zhuyin, please see the following rules and examples
1. Please insert a space between words
2. Please use v instead of ü for pinyin
3. Please use number for pinyin's tone (no number for neutral tone)

Example1:
Word: 爸爸
Pinyin: ba4 ba
Zhuyin: ㄅㄚˋ ㄅㄚ˙

Example2:
Word: 旅遊
Pinyin: lv3 you2
Zhuyin: ㄌㄩˇ ㄧㄡˊ"""
)


class Word:
	def __init__(self, text, pronunciation=""):
		self.text = text
		self.pronunciation = pronunciation


class AddDictionaryEntryDialog(
	gui.contextHelp.ContextHelpMixin,
	wx.Dialog,  # wxPython does not seem to call base class initializer, put last in MRO
):
	helpId = "WordBridgeDictionary"

	def __init__(self, parent):
		# Translators: This is the label for the add symbol dialog.
		super().__init__(parent, title=_("Add Entry"))
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		sHelper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

		# Translators: This is the label for the edit field in the add symbol dialog.
		addPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(2, 2)

		addWordTextLabel = wx.StaticText(addPanel, label=_("Selected &Word:"))
		sizer.Add(addWordTextLabel, pos=(0, 0), flag=wx.LEFT, border=10)
		self.addWordEdit = wx.TextCtrl(
			addPanel,
		)
		sizer.Add(self.addWordEdit, pos=(0, 1))

		self.pronunciationTextxtLabel = wx.StaticText(addPanel, label=_("&Pronunciation (Pinyin or Zhuyin):"))
		sizer.Add(self.pronunciationTextxtLabel, pos=(1, 0), flag=wx.LEFT, border=10)
		self.addPronunciationEdit = wx.TextCtrl(
			addPanel,
		)
		sizer.Add(self.addPronunciationEdit, pos=(1, 1))

		addPanel.SetSizer(sizer)
		sizer.Fit(self)
		sHelper.addItem(addPanel)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))

		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		mainSizer.Fit(self)
		self.SetSizer(mainSizer)
		self.addWordEdit.SetFocus()
		self.CentreOnScreen()


class DictionaryEntryDialog(SettingsDialog):
	helpId = "WordBridgeDictionary"

	def __init__(self, parent):
		self.path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.csv')
		data = []
		with open(self.path, 'r', encoding='utf-8') as file:
			reader = csv.DictReader(file)
			for row in reader:
				data.append(row)
		self.data = data

		self.title = _("WordBridge Dictionary")
		super(DictionaryEntryDialog, self).__init__(
			parent,
			resizeable=True,
		)

	def makeSettings(self, settingsSizer):
		self.filteredWords = self.words = [Word(item["text"], item["pronunciation"]) for item in self.data]
		self.pendingRemovals = {}

		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		# Translators: The label of a text field to search for symbols in the speech symbols dialog.
		filterText = _("&Filter by:")
		self.filterEdit = sHelper.addLabeledControl(
			labelText=filterText,
			wxCtrlClass=wx.TextCtrl,
			size=(self.scaleSize(310), -1),
		)
		self.filterEdit.Bind(wx.EVT_TEXT, self.onFilterEditTextChange)

		sHelper.addItem(
			wx.StaticText(
				self,
				label=_("User can add words to improve the accuracy of these terms.\n") +\
						_("Please press Help button for more details.")
			)
		)

		# Translators: The label for symbols list in symbol pronunciation dialog.
		wordsText = _("&Words")
		self.wordsList = sHelper.addLabeledControl(
			wordsText,
			nvdaControls.AutoWidthColumnListCtrl,
			autoSizeColumn=2,  # The replacement column is likely to need the most space
			itemTextCallable=self.getItemTextForList,
			style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_VIRTUAL,
		)

		# Translators: The label for a column in symbols list used to identify a word.
		self.wordsList.AppendColumn(_("Word"), width=self.scaleSize(150))
		# Translators: The label for a column in symbols list used to identify a pronunciation.
		self.wordsList.AppendColumn(_("Pronunciation (Pinyin or Zhuyin)"))

		self.wordsList.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.onListItemFocused)

		# Translators: The label for the group of controls in symbol pronunciation dialog to change the pronunciation of a word.
		changeWordText = _("Change selected word")
		changeWordSizer = wx.StaticBoxSizer(wx.VERTICAL, self, label=changeWordText)
		changeWordGroup = guiHelper.BoxSizerHelper(self, sizer=changeWordSizer)
		changeWordHelper = sHelper.addItem(changeWordGroup)

		# Used to ensure that event handlers call Skip(). Not calling skip can cause focus problems for controls. More
		# generally the advice on the wx documentation is: "In general, it is recommended to skip all non-command events
		# to allow the default handling to take place. The command events are, however, normally not skipped as usually
		# a single command such as a button click or menu item selection must only be processed by one handler."
		def skipEventAndCall(handler):
			def wrapWithEventSkip(event):
				if event:
					event.Skip()
				return handler()

			return wrapWithEventSkip

		# Translators: The label for the edit field in dialog to change the pronunciation text of a word.
		modifyPanel = wx.Panel(self)
		sizer = wx.GridBagSizer(2, 2)

		self.wordTextLabel = wx.StaticText(modifyPanel, label=_("Selected &Word:"))
		sizer.Add(self.wordTextLabel, pos=(0, 0), flag=wx.LEFT, border=10)
		self.wordEdit = wx.TextCtrl(
			modifyPanel,
			size=(self.scaleSize(250), -1),
		)
		self.wordEdit.Bind(wx.EVT_TEXT, skipEventAndCall(self.onWordEdited))
		sizer.Add(self.wordEdit, pos=(0, 1))

		self.pronunciationTextxtLabel = wx.StaticText(modifyPanel, label=_("&Pronunciation (Pinyin or Zhuyin): "))
		sizer.Add(self.pronunciationTextxtLabel, pos=(1, 0), flag=wx.LEFT, border=10)
		self.pronunciationEdit = wx.TextCtrl(
			modifyPanel,
			size=(self.scaleSize(250), -1),
		)
		self.pronunciationEdit.Bind(wx.EVT_TEXT, skipEventAndCall(self.onWordEdited))
		sizer.Add(self.pronunciationEdit, pos=(1, 1))

		modifyPanel.SetSizer(sizer)
		sizer.Fit(self)
		changeWordHelper.addItem(modifyPanel)

		bHelper = sHelper.addItem(guiHelper.ButtonHelper(orientation=wx.HORIZONTAL))
		# Translators: The label for a button in the Symbol Pronunciation dialog to add a new symbol.
		addButton = bHelper.addButton(self, label=_("&Add"))

		# Translators: The label for a button in the Symbol Pronunciation dialog to remove a symbol.
		self.removeButton = bHelper.addButton(self, label=_("Re&move"))
		self.removeButton.Disable()

		self.helpButton = bHelper.addButton(self, label=_("&Help"))

		addButton.Bind(wx.EVT_BUTTON, self.OnAddClick)
		self.removeButton.Bind(wx.EVT_BUTTON, self.OnRemoveClick)
		self.helpButton.Bind(wx.EVT_BUTTON, self.OnHelpClick)

		# Populate the unfiltered list with symbols.
		self.filter()

	def postInit(self):
		self.wordsList.SetFocus()

	def filter(self, filterText=""):
		NONE_SELECTED = -1
		previousSelectionValue = None
		previousIndex = self.wordsList.GetFirstSelected()  # may return NONE_SELECTED
		if previousIndex != NONE_SELECTED:
			previousSelectionValue = self.filteredWords[previousIndex]

		if not filterText:
			self.filteredWords = self.words
		else:
			# Do case-insensitive matching by lowering both filterText and each symbols's text.
			filterText = filterText.lower()
			self.filteredWords = [
				word
				for word in self.words
				if filterText in word.text.lower() or filterText in word.pronunciation.lower()
			]
		self.wordsList.ItemCount = len(self.filteredWords)

		# sometimes filtering may result in an empty list.
		if not self.wordsList.ItemCount:
			self.editingItem = None
			# disable the "change symbol" controls, since there are no items in the list.
			self.pronunciationEdit.Disable()
			self.removeButton.Disable()
			return  # exit early, no need to select an item.

		# If there was a selection before filtering, try to preserve it
		newIndex = 0  # select first item by default.
		if previousSelectionValue:
			try:
				newIndex = self.filteredWords.index(previousSelectionValue)
			except ValueError:
				pass

		# Change the selection
		self.wordsList.Select(newIndex)
		self.wordsList.Focus(newIndex)
		# We don't get a new focus event with the new index.
		self.wordsList.sendListItemFocusedEvent(newIndex)

	def getItemTextForList(self, item, column):
		word = self.filteredWords[item]
		if column == 0:
			return word.text
		elif column == 1:
			return word.pronunciation
		else:
			raise ValueError("Unknown column: %d" % column)

	def onWordEdited(self):
		if self.editingItem is not None:
			# Update the symbol the user was just editing.
			item = self.editingItem
			word = self.filteredWords[item]
			word.text = self.wordEdit.Value
			word.pronunciation = self.pronunciationEdit.Value

	def onListItemFocused(self, evt):
		# Update the editing controls to reflect the newly selected symbol.
		item = evt.GetIndex()
		word = self.filteredWords[item]
		self.editingItem = item
		# ChangeValue and Selection property used because they do not cause EVNT_CHANGED to be fired.
		self.wordEdit.ChangeValue(word.text)
		self.pronunciationEdit.ChangeValue(word.pronunciation)

		self.removeButton.Enabled = True
		self.pronunciationEdit.Enable()
		evt.Skip()

	def OnAddClick(self, evt):
		with AddDictionaryEntryDialog(self) as entryDialog:
			if entryDialog.ShowModal() != wx.ID_OK:
				return
			text = entryDialog.addWordEdit.GetValue()
			pronunciation = entryDialog.addPronunciationEdit.GetValue()
			if not text:
				return
		# Clean the filter, so we can select the new entry.
		self.filterEdit.Value = ""
		self.filter()
		for index, word in enumerate(self.words):
			if text == word.text:
				gui.messageBox(
					# Translators: An error reported in the Symbol Pronunciation dialog
					# when adding a symbol that is already present.
					_('Word "%s" is already present.') % text,
					# Translators: title of an error message
					_("Error"),
					wx.OK | wx.ICON_ERROR,
				)
				self.wordsList.Select(index)
				self.wordsList.Focus(index)
				self.wordsList.SetFocus()
				return
		addedWord = Word(text, pronunciation)
		try:
			del self.pendingRemovals[text]
		except KeyError:
			pass
		self.words.append(addedWord)
		self.wordsList.ItemCount = len(self.words)
		index = self.wordsList.ItemCount - 1
		self.wordsList.Select(index)
		self.wordsList.Focus(index)
		# We don't get a new focus event with the new index.
		self.wordsList.sendListItemFocusedEvent(index)
		self.wordsList.SetFocus()

	def OnRemoveClick(self, evt):
		index = self.wordsList.GetFirstSelected()
		word = self.filteredWords[index]
		self.pendingRemovals[word.text] = word
		del self.filteredWords[index]
		if self.filteredWords is not self.words:
			self.words.remove(word)
		self.wordsList.ItemCount = len(self.filteredWords)
		# sometimes removing may result in an empty list.
		if not self.wordsList.ItemCount:
			self.editingItem = None
			# disable the "change symbol" controls, since there are no items in the list.
			self.pronunciationEdit.Disable()
			self.removeButton.Disable()
		else:
			index = min(index, self.wordsList.ItemCount - 1)
			self.wordsList.Select(index)
			self.wordsList.Focus(index)
			# We don't get a new focus event with the new index.
			self.wordsList.sendListItemFocusedEvent(index)
		self.wordsList.SetFocus()

	def OnHelpClick(self, evt):
		dialog = wx.Dialog(self, title="Guideline for Adding Words", size=(1200, 900))
		dialogSizer = wx.BoxSizer(wx.VERTICAL)

		textctrl = wx.TextCtrl(dialog, value=GUIDELINE_TEXT, style=wx.TE_MULTILINE | wx.TE_READONLY)
		dialogSizer.Add(textctrl, 1, wx.ALL | wx.EXPAND, 10)
		dialog.SetSizer(dialogSizer)
		textctrl.SetFocus()

		closeButton = wx.Button(dialog, label=_("Close"))
		closeButton.Bind(wx.EVT_BUTTON, lambda event: dialog.EndModal(wx.ID_OK))
		dialogSizer.Add(closeButton, 0, wx.ALL | wx.CENTER, 10)

		dialog.ShowModal()
		dialog.Destroy()

	def onOk(self, evt):
		self.onWordEdited()
		self.editingItem = None

		data = []
		for word in self.words:
			# if not word.pronunciation:
				# continue
			data.append({
				"text": word.text,
				"pronunciation": word.pronunciation,
			})

		with open(self.path, 'w', encoding='utf-8', newline='') as file:
			writer = csv.DictWriter(file, fieldnames=["text", "pronunciation"])
			writer.writeheader()
			for row in data:
				writer.writerow(row)

		super(DictionaryEntryDialog, self).onOk(evt)

	def _refreshVisibleItems(self):
		count = self.wordsList.GetCountPerPage()
		first = self.wordsList.GetTopItem()
		self.wordsList.RefreshItems(first, first + count)

	def onFilterEditTextChange(self, evt):
		self.filter(self.filterEdit.Value)
		self._refreshVisibleItems()
		evt.Skip()
