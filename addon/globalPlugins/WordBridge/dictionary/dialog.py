import gui
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsDialog
import wx

import csv
import os


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
		symbolText = _("&Word:")
		self.identifierTextCtrl = sHelper.addLabeledControl(symbolText, wx.TextCtrl)

		sHelper.addDialogDismissButtons(self.CreateButtonSizer(wx.OK | wx.CANCEL))

		mainSizer.Add(sHelper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		mainSizer.Fit(self)
		self.SetSizer(mainSizer)
		self.identifierTextCtrl.SetFocus()
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
		self.wordsList.AppendColumn(_("Pronunciation"))

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
		wordText = _("&Word")
		self.wordEdit = changeWordHelper.addLabeledControl(
			labelText=wordText,
			wxCtrlClass=wx.TextCtrl,
			size=(self.scaleSize(300), -1),
		)
		self.wordEdit.Bind(wx.EVT_TEXT, skipEventAndCall(self.onWordEdited))

		pronunciationText = _("&Pronunciation")
		self.pronunciationEdit = changeWordHelper.addLabeledControl(
			labelText=pronunciationText,
			wxCtrlClass=wx.TextCtrl,
			size=(self.scaleSize(300), -1),
		)
		self.pronunciationEdit.Bind(wx.EVT_TEXT, skipEventAndCall(self.onWordEdited))

		bHelper = sHelper.addItem(guiHelper.ButtonHelper(orientation=wx.HORIZONTAL))
		# Translators: The label for a button in the Symbol Pronunciation dialog to add a new symbol.
		addButton = bHelper.addButton(self, label=_("&Add"))

		# Translators: The label for a button in the Symbol Pronunciation dialog to remove a symbol.
		self.removeButton = bHelper.addButton(self, label=_("Re&move"))
		self.removeButton.Disable()

		addButton.Bind(wx.EVT_BUTTON, self.OnAddClick)
		self.removeButton.Bind(wx.EVT_BUTTON, self.OnRemoveClick)

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
			text = entryDialog.identifierTextCtrl.GetValue()
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
		addedWord = Word(text)
		try:
			del self.pendingRemovals[text]
		except KeyError:
			pass
		addedWord.pronunciation = ""
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
