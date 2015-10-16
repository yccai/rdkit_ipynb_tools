#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#####
Tools
#####

*Created on Thu Jul  2 10:07:56 2015 by A. Pahl*

A set for tools to use with the `RDKit <http://rdkit.org>`_ in the IPython notebook.
"""

# TODO: jsme: check for local installation, and use internet when not found
# TODO: Mol_List remove duplicate entries (by id, by structure)

from __future__ import print_function, division

from rdkit.Chem import AllChem as Chem
from rdkit.Chem import Draw, rdFMCS
import rdkit.Chem.Descriptors as Desc
Draw.DrawingOptions.atomLabelFontFace = "DejaVu Sans"
Draw.DrawingOptions.atomLabelFontSize = 18

import time
import sys
import base64
import os.path as op
import random

from PIL import Image, ImageChops

import pandas as pd

from . import html_templates as html
from . import hc_tools as hct

from IPython.html import widgets
from IPython.core.display import HTML, display

if sys.version_info[0] > 2:
    PY3 = True
    from io import BytesIO as IO
else:
    PY3 = False
    from cStringIO import StringIO as IO

try:
    from misc_tools import apl_tools as apt
    AP_TOOLS = True
except ImportError:
    AP_TOOLS = False

try:
    from Contrib.SA_Score import sascorer
    SASCORER = True
except ImportError:
    print("* SA scorer not available. RDKit's Contrib dir needs to be in the Python import path...")
    SASCORER = False


if AP_TOOLS:
    #: Library version
    VERSION = apt.get_commit(__file__)
    # I use this to keep track of the library versions I use in my project notebooks
    print("{:45s} (commit: {})".format(__name__, VERSION))
else:
    print("{:45s} ({})".format(__name__, time.strftime("%y%m%d-%H:%M", time.localtime(op.getmtime(__file__)))))

BGCOLOR = "#94CAEF"

JSME_OPTIONS = {"css": ["css/style.css", "css/collapsible_list.css"],
                "scripts": ["lib/jsme/jsme.nocache.js"]}

TBL_JAVASCRIPT = '''<script type="text/javascript">

function toggleCpd(cpdIdent)
{{
  listPos = document.id_list{ts}.data.value.indexOf(cpdIdent);
  cpdIdentCell = document.getElementById(cpdIdent+"_{ts}");
  if (listPos == -1)
  {{
    if (document.id_list{ts}.remark.checked == true)
    {{
      rem = "\\t" + prompt("Remark (Enter for none):", "");
    }}
    else
    {{
      rem = "";
    }}
    document.id_list{ts}.data.value = document.id_list{ts}.data.value + cpdIdent + rem + "\\n";
    cpdIdentCell.style.backgroundColor = "yellow";
  }}
  else
  {{
    removeStr = cpdIdent;
    tempStr2 = document.id_list{ts}.data.value;
    if (listPos > 0) {{
      tempStr1 = tempStr2.substring(0, listPos);
      tempStr2 = tempStr2.substring(listPos, tempStr2.length);
    }} else {{
      tempStr1 = "";
    }}
    listPos = tempStr2.indexOf("\\n");
    if (listPos < tempStr2.length - 1) {{
      tempStr1 = tempStr1 + tempStr2.substring(listPos+1, tempStr2.length)
    }}
    document.id_list{ts}.data.value = tempStr1;
    cpdIdentCell.style.backgroundColor = "{bgcolor}";
  }}
}}


function myShowSelection() {{
  document.location.hash = "#SelectionList";
}}
</script>
'''

ID_LIST = """<br><b><a name="SelectionList">Selection:</a></b>
<form name="id_list{ts}">
<input type="checkbox" name="remark" value="prompt" > Prompt for Remarks<br>
<textarea name="data" cols="70" rows="10"></textarea>
</form>
"""

JSME_FORM = '''<script type="text/javascript" src="lib/jsme/jsme.nocache.js"></script>
<script type="text/javascript">

function jsmeOnLoad() {{
    //arguments: HTML id, width, height (must be string not number!)
    jsmeApplet{ts} = new JSApplet.JSME("appletContainer{ts}", "380px", "340px", {{
                     //optional parameters
                     "options" : "query,hydrogens"
	}});
}}

function onSubmit() {{
    var drawing = jsmeApplet{ts}.smiles();
    // document.getElementById('jsme_smiles{ts}').value = drawing;
    var command = "{var_name} = Chem.MolFromSmiles('" + drawing + "')";
    console.log("Executing Command: " + command);

    var kernel = IPython.notebook.kernel;
    kernel.execute(command);
}}
</script>

<table align="left" style="border: none;">
<tr style="border: none;">
<td id="appletContainer{ts}" style="border: none;"></td>
<td style="vertical-align: bottom; border: none;">
<button onclick="onSubmit()">done !</button>
</td>
</tr>
</table>
'''


class NoFieldTypes(Exception):
    def __str__(self):
        return repr("FieldTypeError: field types could not be extracted from Mol_List")


class Mol_List(list):
    """Enables display of molecule lists as HTML tables in IPython notebook just by-call
    (via _repr_html)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order = None
        self.ia = False


    def __getitem__(self, item):
        result = list.__getitem__(self, item)
        try:
            new_list = Mol_List(result)
            new_list.order = self.order
            return new_list
        except TypeError:
            return result


    def _repr_html_(self):
        id_prop = guess_id_prop(list_fields(self)) if self.ia else None
        return mol_table(self, id_prop=id_prop, order=self.order)


    def _key_get_prop(self, mol, field):
        try:
            val = float(mol.GetProp(field))
        except ValueError: # GetProp value could not be converted to float
            val = mol.GetProp(field)
        except KeyError:   # field is not present in the mol properties
            val = 10000000.0
        return val


    def _get_field_types(self):
        """detect all the property field types and return as dict"""

        print("  > detecting field types...")
        field_types = {}

        if len(self) > 100:
            sdf_sample = random.sample(self, len(self)//2)
        else:
            sdf_sample = self

        for mol in sdf_sample:
            prop_names = mol.GetPropNames()

            for prop in prop_names:
                prop_type = "number"
                prop_str = mol.GetProp(prop)

                try:
                    float(prop_str)
                    if prop.lower().endswith("id"):
                        prop_type = "key"

                except ValueError:
                    prop_type = "str"

                if prop in field_types:
                    if field_types[prop] in ["number", "key"] and prop_type == "str":
                        # "str" overrides everything: if one string is among the values
                        # of a property, all values become type "str"
                        field_types[prop] = prop_type
                else:
                    field_types[prop] = prop_type

        if not field_types:
            raise NoFieldTypes()

        return field_types


    def _calc_d(self):
        self._d = {x: [] for x in self.fields}
        self._d["mol"] = []
        for mol in self:
            if not mol: continue
            img_tag = '<img src="data:image/png;base64,{}" alt="Mol"/>'.format(b64_img(mol))
            self._d["mol"].append(img_tag)

            for prop in self.fields:
                if mol.HasProp(prop):
                    self._d[prop].append(get_value(mol.GetProp(prop)))
                else:
                    self._d[prop].append(None)


    def align(self, mol_or_smiles=None):
        """Align the Mol_list to the common substructure provided as Mol or Smiles.

        Args:
            mol_or_smiles (bool): The substructure to which to align.
                If None, then the method uses rdFMCS to determine the MCSS
                of the Mol_List."""

        align(self, mol_or_smiles)

        # only recalc the molecule dictionary if it is already present, e.g. after a plot
        if hasattr(self, "_d"):
            self._calc_d()



    def write_sdf(self, fn, conf_id=-1):
        """Write Mol_List instance as SD File"""

        writer = Chem.SDWriter(fn)

        # try to save the column order
        first_mol = True
        for mol in self:
            if first_mol:
                order = None
                try:
                    order = self.order
                except AttributeError:
                    pass
                if order:
                    mol.SetProp("order", ";".join(order))

            try:
                mol.GetConformer()
            except ValueError: # no 2D coords... calculate them
                mol.Compute2DCoords()

            writer.write(mol, confId=conf_id)

            # remove the order property again from mol_list
            if first_mol:
                first_mol = False
                mol.ClearProp("order")

        writer.close()


    def sort_list(self, field, reverse=True):
        """Sort the Mol_List according to <field>."""
        self.sort(key=lambda x: self._key_get_prop(x, field), reverse=reverse)


    def mols_with_prop(self, prop):
        """Returns:
            Am iterator of molecules in the list where mol and prop are defined."""

        for mol in self:
            if mol and mol.HasProp(prop):
                yield mol


    def prop_filter(self, query, invert=False, sorted=True, reverse=True, field_types=None):
        """Return a new Mol_List based on the property filtering"""
        result_list = Mol_List()
        mol_counter_out = 0

        if not field_types:
            field_types = self.get_field_types()

        if not field_types:
            print("  # no field type information available! -aborted.")
            return None

        field = None
        for el in query.split():
            if el in field_types:
                field = el
                break

        if not field:
            print("  # field could be extracted from query! -aborted.")
            return None

        print("  > field {} extracted from query: {}.".format(field, query))

        query_mod = query.replace(field, "val")

        for mol_counter_in, mol in enumerate(self):
            if not mol:
                continue
            hit = False
            if field in mol.GetPropNames():
                val = mol.GetProp(field).lower()
                if field_types[field] in ["number", "key"]:
                    try:
                        val_float = float(val)

                    except ValueError:
                        continue

                    val_int = int(val_float)
                    if val_int == val_float:
                        val = val_int
                    else:
                        val = val_float

                if eval(query_mod):
                    hit = True

                if invert:
                    hit = not hit

                if hit:
                    mol_counter_out += 1
                    result_list.append(mol)

        print("  > processed: {:7d}   found: {:6d}".format(mol_counter_in+1, mol_counter_out))

        if sorted:
            result_list.sort_list(field, reverse=reverse)

        return result_list


    def mol_filter(self, smarts, invert=False, add_h=False):
        """Returns a new Mol_List containing the substructure matches"""
        result_list = Mol_List()

        mol_counter_out = 0
        query = Chem.MolFromSmarts(smarts)
        if not query:
            print("* ERROR: could not generate query from SMARTS.")
            return None

        if not add_h and "[H]" in smarts:
            add_h = True
            print("  > explicit hydrogens turned on (add_h = True)")

        for mol_counter_in, mol in enumerate(self):
            if not mol: continue

            hit = False
            if add_h:
                mol_with_h = Chem.AddHs(mol)
                if mol_with_h.HasSubstructMatch(query):
                    hit = True

            else:
                if mol.HasSubstructMatch(query):
                    hit = True

            if invert:
                # reverse logic
                hit = not hit

            if hit:
                mol_counter_out += 1
                result_list.append(mol)

        print("  > processed: {:7d}   found: {:6d}".format(mol_counter_in+1, mol_counter_out))

        return result_list


    def get_ids(self, id_prop=None):
        """Return a list of compound ids"""
        prop_list = list_fields(self)

        if id_prop:
            if not id_prop in prop_list:
                raise LookupError("id_prop not found in data set.")
        else: # try to guess an id_prop
            id_prop = guess_id_prop(prop_list)

        if not id_prop:
            raise LookupError("no id prop could be found in data set.")

        self.id_prop = id_prop
        id_list = []
        for mol in self:
            if mol:
                if mol.HasProp(id_prop):
                    val = get_value(mol.GetProp(id_prop))
                    id_list.append(val)

        return id_list


    def new_list_from_ids(self, id_list, id_prop=None):
        id_all = set(self.get_ids(id_prop))
        id_set = set(id_list)
        id_found = id_set.intersection(id_all)
        id_not_found = id_set - id_all
        if id_not_found:
            print("  not found:", id_not_found)

        new_list = Mol_List()
        for mol in self:
            if mol:
                if mol.HasProp(self.id_prop):
                    val = get_value(mol.GetProp(self.id_prop))
                    if val in id_found:
                        new_list.append(mol)

        return new_list


    def calc_props(self, props):
        """Remove properties from the Mol_List.
        props can be a single property or a list of properties.

        Calculable properties:
            2d, date, formula, hba, hbd, logp, molid, mw, rotb, sa (synthetic accessibility), tpsa

        Synthetic Accessibility (normalized):
            0: hard to synthesize; 1: easy access

            as described in:
                | Estimation of Synthetic Accessibility Score of Drug-like Molecules based on Molecular Complexity and Fragment Contributions
                | *Peter Ertl and Ansgar Schuffenhauer*
                | Journal of Cheminformatics 1:8 (2009) (`link <http://www.jcheminf.com/content/1/1/8>`_)
        """

        if not isinstance(props, list):
            props = [props]

        ctr = 0
        calculated_props = set()
        for mol in self:
            if not mol: continue

            if "2d" in props:
                mol.Compute2DCoords()
                calculated_props.add("2d")
            else:
                try:
                    mol.GetConformer()
                except ValueError: # no 2D coords... calculate them
                    mol.Compute2DCoords()

            if "date" in props:
                mol.SetProp("date", time.strftime("%Y%m%d"))
                calculated_props.add("date")

            if "formula" in props:
                mol.SetProp("formula", Chem.CalcMolFormula(mol))
                calculated_props.add("formula")

            if "hba" in props:
                mol.SetProp("hba", str(Desc.NOCount(mol)))
                calculated_props.add("hba")

            if "hbd" in props:
                mol.SetProp("hbd", str(Desc.NHOHCount(mol)))
                calculated_props.add("hbd")

            if "logp" in props:
                mol.SetProp("logp", "{:.2f}".format(Desc.MolLogP(mol)))
                calculated_props.add("logp")

            if "molid" in props:
                mol.SetProp("molid", str(ctr))
                ctr += 1
                calculated_props.add("molid")

            if "mw" in props:
                mol.SetProp("mw", "{:.2f}".format(Desc.MolWt(mol)))
                calculated_props.add("mw")

            if "rotb" in props:
                mol.SetProp("rotb", str(Desc.NumRotatableBonds(mol)))
                calculated_props.add("rotb")

            if SASCORER and "sa" in props:
                score = sascorer.calculateScore(mol)
                norm_score = 1 - (score / 10)
                mol.SetProp("sa", "{:.2f}".format(norm_score))
                calculated_props.add("sa")

            if "tpsa" in props:
                mol.SetProp("tpsa", str(int(Desc.TPSA(mol))))
                calculated_props.add("tpsa")

        # only recalc the molecule dictionary if it is already present, e.g. after a plot
        if hasattr(self, "_d"):
            self._calc_d()

        not_calculated = set(props) - calculated_props
        if not_calculated:
            print("* these props could not be calculated:", not_calculated)


    def remove_props(self, props):
        """Remove properties from the Mol_List.
        props can be a single property or a list of properties."""

        for mol in self:
            if mol:
                remove_props_from_mol(mol, props)

        # only recalc the molecule dictionary if it is already present, e.g. after a plot
        if hasattr(self, "_d"):
            self._calc_d()


    def copy_prop(self, prop_orig, prop_copy, move=False):
        """Copy or rename a property in the Mol_List."""

        for mol in self.mols_with_prop(prop_orig):
            val_orig = mol.GetProp(prop_orig)
            mol.SetProp(prop_copy, val_orig)
            if move:
                mol.ClearProp(prop_orig)

        # only recalc the molecule dictionary if it is already present, e.g. after a plot
        if hasattr(self, "_d"):
            self._calc_d()


    def rename_prop(self, prop_orig, prop_new):
        """Convenience wrapper around copy_prop"""

        self.copy_prop(prop_orig, prop_new, move=True)


    def remove_dups_by_id(self, id_prop=None):
        """Remove duplicate records by Compound Id.

        Parameters:
            id_prop (None, str): The name of the Id property, if *None*, it will be guessed.

        Returns:
            new Mol_list without the duplicate Ids."""

        new_list = Mol_List()
        id_list = []
        if not id_prop:
            id_prop = guess_id_prop(list_fields(self))
        if not id_prop:
            print("* could not determine Id property.")
            return None

        for mol in self:
            if not mol: continue
            mol_id = mol.GetProp(id_prop)
            if mol_id in id_list: continue
            id_list.append(mol_id)
            new_list.append(mol)

        return new_list


    def remove_dups_by_struct(self):
        """Remove duplicates by structure. Duplicates are determined by Smiles.

        Returns:
            new Mol_List without the duplicate structures."""

        new_list = Mol_List()
        smiles_list = []
        for mol in self:
            if not mol: continue
            smiles = Chem.MolToSmiles(mol)
            if smiles in smiles_list: continue
            smiles_list.append(smiles)
            new_list.append(mol)

        return new_list


    def set_default(self, prop, def_val, condition=None):
        """Set a default value in all mols, in which ``prop`` is either not defined (``condition`` == None) or
        is evaluating ``condition`` to true."""

        if condition and not isinstance(condition, str):
            raise TypeError("condition needs to be of type str.")

        for mol in self:
            if not mol: continue
            if not condition:
                if not mol.HasProp(prop):
                    mol.SetProp(prop, str(def_val))
            else:
                if mol.HasProp(prop):
                    if eval("""{} {}""".format(mol.GetProp(prop), condition)):
                        mol.SetProp(prop, str(def_val))

        # only recalc the molecule dictionary if it is already present, e.g. after a plot
        if hasattr(self, "_d"):
            self._calc_d()


    def table(self, id_prop=None, highlight=None, show_hidden=False, raw=False):
        """Return the Mol_List as HTML table.
        Either as raw HTML (raw==True) or as HTML object for display in IPython notebook.

        Parameters:
            show_hidden (bool): Whether to show hidden properties (name starts with _) or not.
                Defaults to *False*."""

        if not id_prop:
            id_prop = guess_id_prop(list_fields(self)) if self.ia else None
        if raw:
            return mol_table(self, id_prop=id_prop, highlight=highlight, order=self.order, show_hidden=show_hidden)
        else:
            return HTML(mol_table(self, id_prop=id_prop, highlight=highlight, order=self.order))


    def grid(self, props=None, id_prop=None, highlight=None, mols_per_row=5, size=200, raw=False):
        """Return the Mol_List as HTML grid table.
        Either as raw HTML (raw==True) or as HTML object for display in IPython notebook"""
        if not id_prop:
            id_prop = guess_id_prop(list_fields(self)) if self.ia else None
        if raw:
            return mol_sheet(self, props=props, id_prop=id_prop, highlight=highlight,
                             mols_per_row=mols_per_row, size=size)
        else:
            return HTML(mol_sheet(self, props=props, id_prop=id_prop, highlight=highlight,
                             mols_per_row=mols_per_row, size=size))


    def write_table(self, id_prop=None, highlight=None, header=None, summary=None, fn="mol_table.html"):
        html.write(html.page(self.table(id_prop=id_prop, highlight=highlight, raw=True), header=header, summary=summary), fn=fn)


    def write_grid(self, props=None, id_prop=None, highlight=None, mols_per_row=5, size=200, header=None, summary=None, fn="mol_grid.html"):
        html.write(html.page(self.grid(props=props, id_prop=id_prop, highlight=highlight,
                             mols_per_row=mols_per_row, size=size, raw=True), header=header, summary=summary), fn=fn)


    def scatter(self, x, y, r=7, id_prop=None, series_by=None, tooltip="struct"):
        """Displays a Highcharts plot in the IPython Notebook.
        Requires the Highcharts javascript library."""

        if not hasattr(self, "_d"):
            self._calc_d() # calc _d for the first time

        return hct.cpd_scatter(self._d, x, y, r=r, pid=id_prop, series_by=series_by, tooltip=tooltip)


    @property
    def fields(self):
        """A List of properties that are present in the Mol_List (property)."""

        self._fields = list_fields(self)
        return self._fields


    @property
    def d(self):
        """Representation of the Mol_List as a dictionary for plotting (property)."""

        try:
            if len(self) != len(self._d["mol"]):
                self._calc_d()
            return self._d
        except AttributeError:
            self._calc_d()
            return self._d



def autocrop(im, bgcolor="white"):
    if im.mode != "RGB":
        im = im.convert("RGB")
    bg = Image.new("RGB", im.size, bgcolor)
    diff = ImageChops.difference(im, bg)
    bbox = diff.getbbox()
    if bbox:
         return im.crop(bbox)
    return None # no contents


def list_fields(sdf_list):
    field_list = []

    for mol in sdf_list:
        field_list.extend(mol.GetPropNames())

    return list(set(field_list))


def load_sdf(file_name_or_obj="testset.sdf"):
    """Create a Mol_List instance from an SD File.
    Accepts a string filename or a file object as input"""

    if isinstance(file_name_or_obj, str):
        if PY3:
            file_obj = open(file_name_or_obj, "rb")
        else:
            file_obj = open(file_name_or_obj)
    else:
        file_obj = file_name_or_obj

    reader = Chem.ForwardSDMolSupplier(file_obj)

    sdf_list = Mol_List()

    # try to load the column order
    first_mol = True
    for mol in reader:
        if mol:
            if first_mol:
                first_mol = False
                order = None
                try:
                    order = mol.GetProp("order")
                    remove_props_from_mol(mol, "order")
                except KeyError:  # first mol does not contain an order field
                    pass

                if order:
                    try:
                        sdf_list.order = order.split(";")

                    except AttributeError:  # sdf_list is not a Mol_List
                        pass

            sdf_list.append(mol)

    if isinstance(file_name_or_obj, str):
        print("  > sdf {} loaded with {} records.".format(file_name_or_obj.split(".")[0], len(sdf_list)))
    else:
        print("  > sdf loaded with {} records.".format(len(sdf_list)))

    return sdf_list


def remove_props_from_mol(mol, prop_or_propslist):
    if not isinstance(prop_or_propslist, list):
        prop_or_propslist = [prop_or_propslist]
    for prop in prop_or_propslist:
        if prop in mol.GetPropNames():
            mol.ClearProp(prop)


def remove_props(mol_or_sdf_list, props):
    if isinstance(mol_or_sdf_list, list):
        for mol in mol_or_sdf_list:
            if mol:
                remove_props_from_mol(mol, props)
    else:
        remove_props_from_mol(mol_or_sdf_list, props)


def ia_remove_props(mol_list):
    """Interactively remove properties from a Mol_List.
    Uses IPython widgets to display the properties to be selected for removal."""

    all_props = list_fields(mol_list)

    def on_btn_clicked(b):
        remove_props(mol_list, props=list(w_sm.selected_labels))

    w_sm = widgets.SelectMultiple(description="Properties to remove:", options=all_props)
    w_btn = widgets.Button(description="Done !")
    w_btn.on_click(on_btn_clicked)

    w_hb = widgets.HBox(children=[w_sm, w_btn])

    display(w_hb)


def ia_keep_props(mol_list):
    """Interactively keep properties from a Mol_List.
    Uses IPython widgets to display the properties to be selected for keeping."""

    all_props = list_fields(mol_list)

    def on_btn_clicked(b):
        props_to_remove = list(set(all_props) - set(w_sm.selected_labels))
        remove_props(mol_list, props=props_to_remove)

    w_sm = widgets.SelectMultiple(description="Properties to keep:", options=all_props)
    w_btn = widgets.Button(description="Done !")
    w_btn.on_click(on_btn_clicked)

    w_hb = widgets.HBox(children=[w_sm, w_btn])

    display(w_hb)


def align(mol_list, mol_or_smiles=None):
    """Align the Mol_list to the common substructure provided as Mol or Smiles.

    Args:
        mol_list: A list of RDKit molecules.
        mol_or_smiles (bool): The substructure to which to align.
            If None, then the method uses rdFMCS to determine the MCSS
            of the mol_list."""


    if mol_or_smiles == None:
        # determine the MCSS
        mcs = rdFMCS.FindMCS(mol_list)
        if mcs.canceled:
            print("* MCSS function timed out. Please provide a mol_or_smiles to align to.")
            return
        if mcs.smartsString:
            mol_or_smiles = Chem.MolFromSmarts(mcs.smartsString)
        else:
            print("* Could not find MCSS. Please provide a mol_or_smiles to align to.")
            return

    elif isinstance(mol_or_smiles, str):
        mol_or_smiles = Chem.MolFromSmiles(mol_or_smiles)

    try:
        mol_or_smiles.GetConformer()
    except ValueError: # no 2D coords... calculate them
        mol_or_smiles.Compute2DCoords()

    for mol in mol_list:
        if mol:
            Chem.GenerateDepictionMatching2DStructure(mol, mol_or_smiles)


def guess_id_prop(prop_list):  # try to guess an id_prop
    for prop in prop_list:
        if prop.lower().endswith("id"):
            return prop
    return None


def get_value(str_val):
    try:
        val = float(str_val)
        if val == int(val):
            val = int(val)
    except ValueError:
        val = str_val
    return val


def b64_img(mol):
    img_file = IO()
    img = autocrop(Draw.MolToImage(mol))
    img.save(img_file, format='PNG')

    b64 = base64.b64encode(img_file.getvalue())
    if PY3:
        b64 = b64.decode()
    img_file.close()

    return b64



def mol_table(sdf_list, id_prop=None, highlight=None, show_hidden=False, order=None):
    """Parameters:
        sdf_list (Mol_List): List of RDKit molecules
        highlight (dict): Dict of properties (special: *all*) and values to highlight cells,
            e.g. {"activity": "< 50"}
        show_hidden (bool): Whether to show hidden properties (name starts with _) or not.
            Defaults to *False*.
        order (list): A list of substrings to match with the field names for ordering in the table header

    Returns:
        HTML table as TEXT to embed in IPython or a web page."""

    time_stamp = time.strftime("%y%m%d%H%M%S")
    td_opt = {"align": "center"}
    header_opt = {"bgcolor": "#94CAEF"}
    table_list = []
    prop_list = list_fields(sdf_list)

    if isinstance(order, list):
        order_rev = order[:]
        order_rev.reverse()
        for k in order_rev:
            prop_list.sort(key=lambda x: k.lower() in x.lower(), reverse=True)

    if id_prop:
        table_list.append(TBL_JAVASCRIPT.format(ts=time_stamp, bgcolor="transparent"))
        if not id_prop in prop_list:
            raise LookupError("id_prop not found in data set.")
        guessed_id = id_prop
    else: # try to guess an id_prop
        guessed_id = guess_id_prop(prop_list)

    if guessed_id:
        # make sure that the id_prop (or the guessed id prop) is first:
        prop_list.pop(prop_list.index(guessed_id))
        tmp_list = [guessed_id]
        tmp_list.extend(prop_list)
        prop_list = tmp_list

    cells = html.td(html.b("#"), header_opt)
    cells.extend(html.td(html.b("Molecule"), header_opt))
    for prop in prop_list:
        cells.extend(html.td(html.b(prop), header_opt))
    rows = html.tr(cells)


    for idx, mol in enumerate(sdf_list):
        cells = []
        mol_props = mol.GetPropNames()

        if id_prop:
            id_prop_val = mol.GetProp(id_prop)
            cell_opt = {"id": "{}_{}".format(id_prop_val, time_stamp)}
        else:
            cell_opt = {"id": str(idx)}
        cell = html.td(str(idx), cell_opt)
        cells.extend(cell)

        if not mol:
            cells.extend(html.td("no structure"))

        else:
            b64 = b64_img(mol)

            if id_prop:
                img_opt = {"title": "Click to select / unselect",
                           "onclick": "toggleCpd('{}')".format(id_prop_val)}
            else:
                img_opt = {"title": str(idx)}

            img_src = "data:image/png;base64,{}".format(b64)
            cells.extend(html.td(html.img(img_src, img_opt)))

        for prop in prop_list:
            td_opt = {"align": "center"}
            if prop in mol_props:
                if not show_hidden and prop.startswith("_"): continue
                td_opt["title"] = prop
                prop_val = mol.GetProp(prop)
                if highlight:
                    eval_str = None
                    if "*all*" in highlight:
                        if not guessed_id or (guessed_id and prop != guessed_id):
                            eval_str = " ".join([prop_val, highlight["*all*"]])
                    else:
                        if prop in highlight:
                            eval_str = " ".join([prop_val, highlight[prop]])
                    if eval_str and eval(eval_str):
                        td_opt["bgcolor"] = "#99ff99"

                cells.extend(html.td(prop_val, td_opt))
            else:
                cells.extend(html.td("", td_opt))

        rows.extend(html.tr(cells))

    table_list.extend(html.table(rows))

    if id_prop:
        table_list.append(ID_LIST.format(ts=time_stamp))

    # print(table_list)
    return "".join(table_list)


def mol_sheet(sdf_list, props=None, id_prop=None, highlight=None, mols_per_row=4, size=200):
    """input:   list of RDKit molecules
    highlight: dict of properties (a.t.m only one) and values to highlight cells,
    e.g. {"activity": "< 50"}
    order: a list of substrings to match with the field names for ordering in the table header
    returns: HTML table as TEXT with molecules in grid-like layout to embed in IPython or a web page."""

    time_stamp = time.strftime("%y%m%d%H%M%S")
    prop_opt = {"align": "center"}
    td_opt = {"align": "center"}

    header_opt = {"bgcolor": BGCOLOR}
    table_list = []
    prop_list = list_fields(sdf_list)
    if props and not isinstance(props, list):
        props = [props]

    if id_prop:
        table_list.append(TBL_JAVASCRIPT.format(ts=time_stamp, bgcolor=BGCOLOR))
        guessed_id = id_prop
    else: # try to guess an id_prop
        guessed_id = guess_id_prop(prop_list)

    rows = []
    id_cells = []
    mol_cells = []
    prop_cells = []
    for idx, mol in enumerate(sdf_list, 1):
        if guessed_id:
            id_prop_val = mol.GetProp(guessed_id)
            cell_opt = {"id": "{}_{}".format(id_prop_val, time_stamp)}
            cell_opt.update(td_opt)
            cell_opt.update(header_opt)
            id_cells.extend(html.td(id_prop_val, cell_opt))

        if not mol:
            cell = ["no structure"]

        else:
            img_file = IO()
            img = autocrop(Draw.MolToImage(mol, size=(size,size)))
            img.save(img_file, format='PNG')

            b64 = base64.b64encode(img_file.getvalue())
            if PY3:
                b64 = b64.decode()
            img_file.close()

            if id_prop:
                img_opt = {"title": "Click to select / unselect",
                           "onclick": "toggleCpd('{}')".format(id_prop_val)}
            else:
                img_opt = {"title": str(idx)}

            img_src = "data:image/png;base64,{}".format(b64)
            cell = html.img(img_src, img_opt)

        td_opt = {"align": "center"}

        if highlight:
            eval_str = None
            prop = highlight.keys()[0]  # only one highlight key supported a.t.m.
            prop_val = mol.GetProp(prop)
            eval_str = " ".join([prop_val, highlight[prop]])
            if eval_str and eval(eval_str):
                td_opt["bgcolor"] = "#99ff99"

        mol_cells.extend(html.td(cell, td_opt))

        if props:
            prop_values = []
            for prop in props:
                if mol.HasProp(prop):
                    prop_values.append(mol.GetProp(prop))
                else:
                    prop_values.append("n.d.")
            prop_str = "_".join(prop_values)
            prop_cells.extend(html.td(prop_str, prop_opt))

        if idx % mols_per_row == 0:
            if guessed_id:
                rows.extend(html.tr(id_cells))

            rows.extend(html.tr(mol_cells))

            if props:
                rows.extend(html.tr(prop_cells))
            id_cells = []
            mol_cells = []
            prop_cells = []

    if mol_cells:
        if guessed_id:
            rows.extend(html.tr(id_cells))

        rows.extend(html.tr(mol_cells))

        if props:
            rows.extend(html.tr(prop_cells))

    table_list.extend(html.table(rows))

    if props:
        table_list.extend(["<p>properties shown: ", "["+"] _ [".join(props)+"]", "</p>"])

    if id_prop:
        table_list.append(ID_LIST.format(ts=time_stamp))

    # print(table_list)
    return "".join(table_list)


def show_table(sdf_list, id_prop=None, highlight=None, order=None):
    return HTML(mol_table(sdf_list, id_prop, highlight=highlight, order=order))


def show_sheet(sdf_list, props=None, id_prop=None, highlight=None, mols_per_row=4):
    return HTML(mol_sheet(sdf_list, props, id_prop, highlight=highlight, mols_per_row=mols_per_row))


def jsme(name="mol"):
    """displays a JSME molecule editor widget in the notebook
    and stores the resulting mol in the variable that <name> assigns."""

    time_stamp = time.strftime("%y%m%d%H%M%S")

    return HTML(JSME_FORM.format(ts=time_stamp, var_name=name))


def dict_from_sdf_list(sdf_list, id_prop=None, props=None, prop_list=None):
    """Generate a dictionary from the properties of a list of molecules.
    Currently not including the structure.
    If <props> contains a list of property names, then only these properties plus the <id_prop> are returned.
    Returns dict"""

    if not prop_list:
        prop_list = list_fields(sdf_list)

    if id_prop:
        if not id_prop in prop_list:
            raise LookupError("id_prop not found in data set.")
        guessed_id = id_prop
    else:
        guessed_id = guess_id_prop(prop_list)

    if not props:
        props = prop_list
    if guessed_id and not guessed_id in props:
        props.append(guessed_id)

    df_dict = {prop: [] for prop in props}

    for mol in sdf_list:
        mol_props = list(mol.GetPropNames())
        for prop in props:
            if prop in mol_props:
                df_dict[prop].append(get_value(mol.GetProp(prop)))
            else:
                df_dict[prop].append(pd.np.NaN)

    return df_dict


# some convenience functions
def mol_3d(smiles_or_mol):
    """return a 3d optimized molecule from a Smiles or 2d mol input"""
    if isinstance(smiles_or_mol, str):  # input is Smiles
        smiles_or_mol = Chem.MolFromSmiles(smiles_or_mol)

    mh = Chem.AddHs(smiles_or_mol)
    Chem.Compute2DCoords(mh)
    Chem.EmbedMolecule(mh)
    Chem.MMFFOptimizeMolecule(mh)
    return mh


def mol_grid(sdf_list, props, fn=None, mols_per_row=5, sub_img_size=(200, 200)):
    """Draw a molecule grid from the input <sdf_list>. An inline graphics will be returned
    in addition to writing the image to <fn> (if defined).
    The given sdf <props> (as a list) will be concatenated to the molecules' legends."""

    if not isinstance(props, list):
        props = [props]

    legends = []
    for mol in sdf_list:
        leg = [mol.GetProp(prop) for prop in props]
        leg_str = "_".join(leg)
        legends.append(leg_str)

    img = Draw.MolsToGridImage(sdf_list, molsPerRow=mols_per_row, subImgSize=sub_img_size, legends=legends)
    if fn:
        img.save(fn)
    return img


def o3da(input_list, ref, fn="aligned.sdf"):
    """Takes a list of molecules and align them to ref.
    Writes the result as SD file to fn."""
    ref_pymp = Chem.MMFFGetMoleculeProperties(ref)
    mol_list = input_list[:]
    writer = Chem.SDWriter(fn)

    print("N\t\tscore\t\trmsd")
    for ctr, mol in enumerate(mol_list, 1):
        mol_pymp = Chem.MMFFGetMoleculeProperties(mol)
        o3a = Chem.GetO3A(mol, ref, mol_pymp, ref_pymp)
        print("{}\t\t{:.2f}\t\t{:.2f}".format(ctr, o3a.Score(),o3a.Align()))
        writer.write(mol)

    writer.close()
