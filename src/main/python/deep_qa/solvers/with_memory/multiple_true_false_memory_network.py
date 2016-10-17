from typing import Any, Dict, List
from overrides import overrides

from keras.layers import TimeDistributed
from ...data.dataset import Dataset
from ...data.instances.true_false_instance import TrueFalseInstance
from .memory_network import MemoryNetworkSolver


class MultipleTrueFalseMemoryNetworkSolver(MemoryNetworkSolver):
    '''
    This is a MemoryNetworkSolver that is trained on multiple choice questions, instead of
    true/false questions, where the questions are converted into a collection of true/false
    assertions.

    This needs changes to two areas of the code: (1) how the data is preprocessed, and (2) how the
    model is built.

    Instead of getting a list of positive and negative examples, we get a question with labeled
    answer options, only one of which can be true.  We then pass each option through the same
    basic structure as the MemoryNetworkSolver, and use a softmax at the end to get a final answer.

    This essentially just means making the MemoryNetworkSolver model time-distributed everywhere,
    and adding a final softmax.
    '''

    # See comments in MemoryNetworkSolver for more info on this.
    has_sigmoid_entailment = True
    has_multiple_backgrounds = True

    def __init__(self, params: Dict[str, Any]):
        # We don't have any parameters to set that are specific to this class, so we just call the
        # superclass constructor.
        super(MultipleTrueFalseMemoryNetworkSolver, self).__init__(params)

        # Now we set some class-specific member variables.
        self.entailment_choices = ['multiple_choice_mlp']

        # And declare some model-specific variables that will be set later.
        self.num_options = None

    @overrides
    def _get_max_lengths(self) -> Dict[str, int]:
        return {
                'word_sequence_length': self.max_sentence_length,
                'background_sentences': self.max_knowledge_length,
                'num_options': self.num_options,
                }

    @overrides
    def _instance_type(self):
        return TrueFalseInstance

    @overrides
    def _set_max_lengths(self, max_lengths: Dict[str, int]):
        self.max_sentence_length = max_lengths['word_sequence_length']
        self.max_knowledge_length = max_lengths['background_sentences']
        self.num_options = max_lengths['num_options']

    @overrides
    def _set_max_lengths_from_model(self):
        self.max_sentence_length = self.model.get_input_shape_at(0)[0][2]
        self.max_knowledge_length = self.model.get_input_shape_at(0)[1][2]
        self.num_options = self.model.get_input_shape_at(0)[0][1]

    @overrides
    def _get_question_shape(self):
        return (self.num_options, self.max_sentence_length,)

    @overrides
    def _get_background_shape(self):
        return (self.num_options, self.max_knowledge_length, self.max_sentence_length)

    @overrides
    def _get_sentence_encoder(self):
        # TODO(matt): add tests for saving and loading these models, to be sure that these names
        # actually work as expected.  There are currently some Keras bugs stopping those tests from
        # working, though.
        base_sentence_encoder = super(MultipleTrueFalseMemoryNetworkSolver, self)._get_sentence_encoder()
        return TimeDistributed(base_sentence_encoder, name="timedist_%s" % base_sentence_encoder.name)

    @overrides
    def _get_knowledge_axis(self):
        # pylint: disable=no-self-use
        return 2

    @overrides
    def _get_knowledge_selector(self, layer_num: int):
        base_selector = super(MultipleTrueFalseMemoryNetworkSolver, self)._get_knowledge_selector(layer_num)
        return TimeDistributed(base_selector, name="timedist_%s" % base_selector.name)

    @overrides
    def _get_knowledge_combiner(self, layer_num: int):
        base_combiner = super(MultipleTrueFalseMemoryNetworkSolver, self)._get_knowledge_combiner(layer_num)
        return TimeDistributed(base_combiner, name="timedist_%s" % base_combiner.name)

    @overrides
    def _get_memory_updater(self, layer_num: int):
        base_memory_updater = super(MultipleTrueFalseMemoryNetworkSolver, self)._get_memory_updater(layer_num)
        return TimeDistributed(base_memory_updater, name="timedist_%s" % base_memory_updater.name)

    @overrides
    def _get_entailment_input_combiner(self):
        base_combiner = super(MultipleTrueFalseMemoryNetworkSolver, self)._get_entailment_input_combiner()
        return TimeDistributed(base_combiner, name="timedist_%s" % base_combiner.name)

    @overrides
    def _load_dataset_from_files(self, files: List[str]):
        dataset = super(MultipleTrueFalseMemoryNetworkSolver, self)._load_dataset_from_files(files)
        return dataset.to_question_dataset()

    @overrides
    def _handle_debug_output(self, dataset: Dataset, layer_names: List[str], outputs, epoch: int):
        debug_output_file = open("%s_debug_%d.txt" % (self.model_prefix, epoch), "w")
        all_question_scores = None
        all_entailment_scores = None
        all_question_attention_outputs = []
        for i, layer_name in enumerate(layer_names):
            if layer_name.endswith('softmax'):
                all_question_scores = outputs[i]
            elif 'knowledge_selector' in layer_name:
                all_question_attention_outputs.append(outputs[i])
            elif layer_name == 'entailment_scorer':
                all_entailment_scores = outputs[i]
        assert all_question_scores is not None, "You must include the softmax layer in the debug output!"
        assert len(all_question_attention_outputs) > 0, "No attention layer specified; what are you debugging?"
        # Collect values from all hops of attention for a given instance into attention_values.
        for instance_index, instance in enumerate(dataset.instances):
            question_scores = all_question_scores[instance_index]
            question_attention_values = [attention[instance_index] for attention in all_question_attention_outputs]
            if all_entailment_scores is not None:
                entailment_scores = all_entailment_scores[instance_index]
            label = instance.label
            print("Correct answer: %s" % label, file=debug_output_file)
            for option_id, option_instance in enumerate(instance.options):
                option_sentence = option_instance.instance.text
                option_background_info = option_instance.background
                option_score = question_scores[option_id]
                # Remove the attention values for padding
                option_attention_values = [hop_attention_values[option_id]
                                           for hop_attention_values in question_attention_values]
                option_attention_values = [values[-len(option_background_info):]
                                           for values in option_attention_values]
                print("\tOption %d: %s" % (option_id, option_sentence), file=debug_output_file)
                print("\tAssigned score: %.4f" % option_score, file=debug_output_file)
                if all_entailment_scores is not None:
                    option_entailment_score = entailment_scores[option_id]
                    print("\tEntailment score: %.4f" % option_entailment_score, file=debug_output_file)
                print("\tWeights on background:", file=debug_output_file)
                for i, background_i in enumerate(option_background_info):
                    if i >= len(option_attention_values[0]):
                        # This happens when IndexedBackgroundInstance.pad() ignored some
                        # sentences (at the end). Let's ignore them too.
                        break
                    all_hops_attention_i = ["%.4f" % values[i] for values in option_attention_values]
                    print("\t\t%s\t%s" % (" ".join(all_hops_attention_i), background_i),
                          file=debug_output_file)
                print(file=debug_output_file)
        debug_output_file.close()