# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the PyMVPA package for the
#   copyright and license terms.
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Cross-validate a classifier on a dataset"""

__docformat__ = 'restructuredtext'

from mvpa.support.copy import deepcopy

from mvpa.measures.base import DatasetMeasure
from mvpa.datasets.splitters import NoneSplitter
from mvpa.base import warning
from mvpa.misc.state import StateVariable, Harvestable
from mvpa.misc.transformers import GrandMean

if __debug__:
    from mvpa.base import debug


class CrossValidatedTransferError(DatasetMeasure, Harvestable):
    """Classifier cross-validation.

    This class provides a simple interface to cross-validate a classifier
    on datasets generated by a splitter from a single source dataset.

    Arbitrary performance/error values can be computed by specifying an error
    function (used to compute an error value for each cross-validation fold)
    and a combiner function that aggregates all computed error values across
    cross-validation folds.
    """

    results = StateVariable(enabled=False, doc=
       """Store individual results in the state""")
    splits = StateVariable(enabled=False, doc=
       """Store the actual splits of the data. Can be memory expensive""")
    transerrors = StateVariable(enabled=False, doc=
       """Store copies of transerrors at each step. If enabled -
       operates on clones of transerror, but for the last split original
       transerror is used""")
    confusion = StateVariable(enabled=False, doc=
       """Store total confusion matrix (if available)""")
    training_confusion = StateVariable(enabled=False, doc=
       """Store total training confusion matrix (if available)""")
    samples_error = StateVariable(enabled=False,
                        doc="Per sample errors.")


    def __init__(self,
                 transerror,
                 splitter=None,
                 combiner='mean',
                 expose_testdataset=False,
                 harvest_attribs=None,
                 copy_attribs='copy',
                 **kwargs):
        """
        :Parameters:
          transerror: TransferError instance
            Provides the classifier used for cross-validation.
          splitter: Splitter | None
            Used to split the dataset for cross-validation folds. By
            convention the first dataset in the tuple returned by the
            splitter is used to train the provided classifier. If the
            first element is 'None' no training is performed. The second
            dataset is used to generate predictions with the (trained)
            classifier. If `None` (default) an instance of
            :class:`~mvpa.datasets.splitters.NoneSplitter` is used.
          combiner: Functor | 'mean'
            Used to aggregate the error values of all cross-validation
            folds. If 'mean' (default) the grand mean of the transfer
            errors is computed.
          expose_testdataset: bool
           In the proper pipeline, classifier must not know anything
           about testing data, but in some cases it might lead only
           to marginal harm, thus migth wanted to be enabled (provide
           testdataset for RFE to determine stopping point).
          harvest_attribs: list of basestr
            What attributes of call to store and return within
            harvested state variable
          copy_attribs: None | basestr
            Force copying values of attributes on harvesting
          **kwargs:
            All additional arguments are passed to the
            :class:`~mvpa.measures.base.DatasetMeasure` base class.
        """
        DatasetMeasure.__init__(self, **kwargs)
        Harvestable.__init__(self, harvest_attribs, copy_attribs)

        if splitter is None:
            self.__splitter = NoneSplitter()
        else:
            self.__splitter = splitter

        if combiner == 'mean':
            self.__combiner = GrandMean
        else:
            self.__combiner = combiner

        self.__transerror = transerror
        self.__expose_testdataset = expose_testdataset

# TODO: put back in ASAP
#    def __repr__(self):
#        """String summary over the object
#        """
#        return """CrossValidatedTransferError /
# splitter: %s
# classifier: %s
# errorfx: %s
# combiner: %s""" % (indentDoc(self.__splitter), indentDoc(self.__clf),
#                      indentDoc(self.__errorfx), indentDoc(self.__combiner))


    def _call(self, dataset):
        """Perform cross-validation on a dataset.

        'dataset' is passed to the splitter instance and serves as the source
        dataset to generate split for the single cross-validation folds.
        """
        # store the results of the splitprocessor
        results = []
        self.states.splits = []

        # local bindings
        states = self.states
        clf = self.__transerror.clf
        expose_testdataset = self.__expose_testdataset

        # what states to enable in terr
        terr_enable = []
        for state_var in ['confusion', 'training_confusion', 'samples_error']:
            if states.isEnabled(state_var):
                terr_enable += [state_var]

        # charge states with initial values
        summaryClass = clf._summaryClass
        clf_hastestdataset = hasattr(clf, 'testdataset')

        self.states.confusion = summaryClass()
        self.states.training_confusion = summaryClass()
        self.states.transerrors = []
        self.states.samples_error = dict([(id, []) for id in dataset.origids])

        # enable requested states in child TransferError instance (restored
        # again below)
        if len(terr_enable):
            self.__transerror.states._changeTemporarily(
                enable_states=terr_enable)

        # We better ensure that underlying classifier is not trained if we
        # are going to deepcopy transerror
        if states.isEnabled("transerrors"):
            self.__transerror.untrain()

        # splitter
        for split in self.__splitter(dataset):
            # only train classifier if splitter provides something in first
            # element of tuple -- the is the behavior of TransferError
            if states.isEnabled("splits"):
                self.states.splits.append(split)

            if states.isEnabled("transerrors"):
                # copy first and then train, as some classifiers cannot be copied
                # when already trained, e.g. SWIG'ed stuff
                lastsplit = None
                for ds in split:
                    if ds is not None:
                        lastsplit = ds._dsattr['lastsplit']
                        break
                if lastsplit:
                    # only if we could deduce that it was last split
                    # use the 'mother' transerror
                    transerror = self.__transerror
                else:
                    # otherwise -- deep copy
                    transerror = deepcopy(self.__transerror)
            else:
                transerror = self.__transerror

            # assign testing dataset if given classifier can digest it
            if clf_hastestdataset and expose_testdataset:
                clf.testdataset = split[1]
                pass

            # run the beast
            result = transerror(split[1], split[0])

            # unbind the testdataset from the classifier
            if clf_hastestdataset and expose_testdataset:
                clf.testdataset = None

            # next line is important for 'self._harvest' call
            self._harvest(locals())

            # XXX Look below -- may be we should have not auto added .?
            #     then transerrors also could be deprecated
            if states.isEnabled("transerrors"):
                self.states.transerrors.append(transerror)

            # XXX: could be merged with next for loop using a utility class
            # that can add dict elements into a list
            if states.isEnabled("samples_error"):
                for k, v in \
                  transerror.states.samples_error.iteritems():
                    self.states.samples_error[k].append(v)

            # pull in child states
            for state_var in ['confusion', 'training_confusion']:
                if states.isEnabled(state_var):
                    states[state_var].value.__iadd__(
                        transerror.states[state_var].value)

            if __debug__:
                debug("CROSSC", "Split #%d: result %s" \
                      % (len(results), `result`))
            results.append(result)

        # Since we could have operated with a copy -- bind the last used one back
        self.__transerror = transerror

        # put states of child TransferError back into original config
        if len(terr_enable):
            self.__transerror.states._resetEnabledTemporarily()

        self.states.results = results
        """Store state variable if it is enabled"""

        # Provide those labels_map if appropriate
        try:
            if states.isEnabled("confusion"):
                states.confusion.labels_map = dataset.labels_map
            if states.isEnabled("training_confusion"):
                states.training_confusion.labels_map = dataset.labels_map
        except:
            pass

        return self.__combiner(results)


    splitter = property(fget=lambda self:self.__splitter,
                        doc="Access to the Splitter instance.")
    transerror = property(fget=lambda self:self.__transerror,
                        doc="Access to the TransferError instance.")
    combiner = property(fget=lambda self:self.__combiner,
                        doc="Access to the configured combiner.")
