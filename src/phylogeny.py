#!/usr/bin/env python
from __future__ import print_function, division
import sys, os, argparse, glob
from collections import OrderedDict, defaultdict
from Bio.SeqIO.FastaIO import SimpleFastaParser

import pandas as pd

# Soothsayer Ecosystem
from genopype import *
from soothsayer_utils import *

pd.options.display.max_colwidth = 100
# from tqdm import tqdm
__program__ = os.path.split(sys.argv[0])[-1]
__version__ = "2022.06.22"


# Assembly
def preprocess( input_filepaths, output_filepaths, output_directory, directories, opts):

    if not os.path.exists(os.path.join(directories["checkpoints"], "0__preprocessing")):

        # If --proteins is a directory turn into a list
        if os.path.isdir(opts.proteins):
            filepaths = glob.glob(os.path.join(opts.proteins, "*.{}".format(opts.extension)))
            df = pd.DataFrame(index=filepaths)
        # If proteins is a table or list
        else:
            df = pd.read_csv(opts.proteins, sep="\t", index_col=0, header=None)
        assert df.shape[1] in {0,1}, "Must either be 1 (for list) or 2 (for table) columns"
        proteins = dict()
        if df.shape[1] == 1:
            proteins = df.iloc[:,0].dropna().to_dict()
        else:
            for path in df.index:
                id_mag = path.split("/")[-1][:-1*(len(opts.extension) + 1)]
                assert id_mag not in proteins, "--proteins has non-unique MAG identifiers"
                proteins[id_mag] = path 
        proteins = pd.Series(proteins)

        # Write files
        proteins.to_frame().to_csv(os.path.join(directories["project"], "proteins.tsv"), sep="\t", header=None)


        os.makedirs(os.path.join(output_directory, "proteins"), exist_ok=True)

        # Proteins
        for id_mag, path in proteins.items():
                src = os.path.realpath(path)
                dst = os.path.join(os.path.join(output_directory, "proteins", "{}.faa".format(id_mag)))
                os.symlink(src,dst)

        with open(os.path.join(directories["project"], "proteins.list" ), "w") as f:
            for fp in glob.glob(os.path.join(os.path.join(output_directory, "proteins","*.faa" ))):
                print(fp, file=f)

        # Write proteins
        with open(os.path.join(directories["tmp"], "proteins.faa" ), "w") as f_out:
            for id_mag, path in proteins.items():
                with open(path, "r") as f_in:
                    for header, seq in SimpleFastaParser(f_in):
                        id_record = header.split(" ")[0]
                        print(">{}|--|{}\n{}".format(id_mag, id_record, seq), file=f_out)

    return []


# HMMSearch
def get_hmmsearch_cmd( input_filepaths, output_filepaths, output_directory, directories, opts):
    # Command

    # Command
    cmd = [
        "(",
        os.environ["hmmsearch"],
        "--tblout {}".format(os.path.join(output_directory, "output.tsv")),
        "--cpu {}".format(opts.n_jobs),
        "--seed {}".format(opts.random_state + 1),
        "--{}".format(opts.hmmsearch_threshold) if opts.hmmsearch_threshold == "e" else "-E {}".format(opts.hmmsearch_evalue),
        opts.database_hmm,
        os.path.join(directories["tmp"], "proteins.faa"),
        "|",
        'grep "^{}:"'.format({"accession":"Accession", "name":"Query"}[opts.hmm_marker_field]),
        ")",
        "&&",
        os.environ["partition_hmmsearch.py"],
        "-i {}".format(os.path.join(output_directory, "output.tsv")),
        "-a {}".format(os.path.join(directories["tmp"], "proteins.faa")),
        "-o {}".format(output_directory),
        '-d "|--|"',
        "-f {}".format(opts.hmm_marker_field),
    ]
    if opts.scores_cutoff:
        cmd += [ 
            "-s {}".format(opts.scores_cutoff),
        ]

    return cmd


# MUSCLE
def get_msa_cmd( input_filepaths, output_filepaths, output_directory, directories, opts):
    # Command

    cmd = [
"""
# MUSCLE
cut -f1 %s | %s -j %d 'echo "[MUSCLE] {}" && zcat "%s/{}.faa.gz" | %s -out %s/{}.msa %s'

# ClipKIT
cut -f1 %s | %s -j %d 'echo "[ClipKIT] {}"  &&  %s %s/{}.msa -m %s -o %s/{}.msa.clipkit %s'

# Concatenate
%s -i %s -x msa.clipkit -o %s/concatenated_alignment.fasta --minimum_genomes_aligned_ratio %f  --minimum_markers_aligned_ratio %f --prefiltered_alignment_table %s --boolean_alignment_table %s
"""%( 
    # MUSCLE
    os.path.join(directories[("intermediate",  "1__hmmsearch")], "markers.tsv"),
    os.environ["parallel"],
    opts.n_jobs,
    directories[("intermediate",  "1__hmmsearch")],
    os.environ["muscle"],
    output_directory,
    opts.muscle_options,

    # ClipKIT
    os.path.join(directories[("intermediate",  "1__hmmsearch")], "markers.tsv"),
    os.environ["parallel"],
    opts.n_jobs,
    os.environ["clipkit"],
    output_directory,
    opts.clipkit_mode,
    output_directory,
    opts.clipkit_options,

    # Concatenate
    os.environ["merge_msa.py"],
    output_directory,
    output_directory,
    opts.minimum_genomes_aligned_ratio,
    opts.minimum_markers_aligned_ratio,
    os.path.join(output_directory, "prefiltered_alignment_table.tsv.gz"),
    os.path.join(output_directory, "alignment_table.boolean.tsv.gz"),
    )
    ]
# """

# for ID_MARKER in $(cut -f1 %s);
#     do echo $ID_MARKER; 
#     FAA=%s/${ID_MARKER}.faa.gz 

#     # Run MUSCLE
#     zcat ${FAA} | %s -out %s/${ID_MARKER}.msa %s


#     # Run ClipKIT
#     %s %s/${ID_MARKER}.msa -m %s -o %s/${ID_MARKER}.msa.clipkit %s

#     done
# """%(
#     os.path.join(directories[("intermediate",  "1__hmmsearch")], "markers.tsv"),
#     directories[("intermediate",  "1__hmmsearch")],
#     os.environ["muscle"],
#     output_directory,
#     opts.muscle_options,
#     os.environ["clipkit"],
#     output_directory,
#     opts.clipkit_mode,
#     output_directory,
#     opts.clipkit_options,
#     ),
#     ]
    return cmd

# FastTree
def get_fasttree_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):

    # Command
    cmd = [
        os.environ["fasttree"],
        opts.fasttree_options,
        input_filepaths[0],
        ">",
        output_filepaths[0],
    ]
    return cmd


# IQTree
def get_iqtree_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):
    # iqtree -s ${output_dir}/Aligned_SCGs_mod_names.faa -nt $num_jobs -mset WAG,LG -bb 1000 -pre iqtree_out

    # Command
    cmd = [
        os.environ["iqtree"],
        "-s {}".format(input_filepaths[0]),
        "-nt AUTO",
        "-ntmax {}".format(opts.n_jobs),
        "-mset {}".format(opts.iqtree_mset),
        "-m {}".format(opts.iqtree_model),
        "-bb {}".format(opts.iqtree_bootstraps),
        "-pre {}".format(os.path.join(output_directory, "output")),
        "--seed {}".format(opts.random_state), 
    ]
    return cmd


# Symlink
def get_symlink_cmd(input_filepaths, output_filepaths, output_directory, directories, opts):
    
    # Command
    cmd = ["("]
    for filepath in input_filepaths:
        # cmd.append("ln -f -s {} {}".format(os.path.realpath(filepath), os.path.realpath(output_directory)))
        cmd.append("ln -f -s {} {}".format(os.path.realpath(filepath), output_directory))
        cmd.append("&&")
    cmd[-1] = ")"
    return cmd

# ============
# Run Pipeline
# ============
# Set environment variables
def add_executables_to_environment(opts):
    """
    Adapted from Soothsayer: https://github.com/jolespin/soothsayer
    """
    accessory_scripts = set([ 
        "partition_hmmsearch.py",
        "merge_msa.py",
    ])

    
    required_executables={
                # 1
                "hmmsearch",
                "muscle",
                "clipkit",
                "parallel",
                "fasttree",
                "iqtree",

     } | accessory_scripts

    if opts.path_config == "CONDA_PREFIX":
        executables = dict()
        for name in required_executables:
            executables[name] = os.path.join(os.environ["CONDA_PREFIX"], "bin", name)
    else:
        if opts.path_config is None:
            opts.path_config = os.path.join(opts.script_directory, "veba_config.tsv")
        opts.path_config = format_path(opts.path_config)
        assert os.path.exists(opts.path_config), "config file does not exist.  Have you created one in the following directory?\n{}\nIf not, either create one, check this filepath:{}, or give the path to a proper config file using --path_config".format(opts.script_directory, opts.path_config)
        assert os.stat(opts.path_config).st_size > 1, "config file seems to be empty.  Please add 'name' and 'executable' columns for the following program names: {}".format(required_executables)
        df_config = pd.read_csv(opts.path_config, sep="\t")
        assert {"name", "executable"} <= set(df_config.columns), "config must have `name` and `executable` columns.  Please adjust file: {}".format(opts.path_config)
        df_config = df_config.loc[:,["name", "executable"]].dropna(how="any", axis=0).applymap(str)
        # Get executable paths
        executables = OrderedDict(zip(df_config["name"], df_config["executable"]))
        assert required_executables <= set(list(executables.keys())), "config must have the required executables for this run.  Please adjust file: {}\nIn particular, add info for the following: {}".format(opts.path_config, required_executables - set(list(executables.keys())))

    # Display
    for name in sorted(accessory_scripts):
        executables[name] = "python " + os.path.join(opts.script_directory, "scripts", name)
    print(format_header( "Adding executables to path from the following source: {}".format(opts.path_config), "-"), file=sys.stdout)
    for name, executable in executables.items():
        if name in required_executables:
            print(name, executable, sep = " --> ", file=sys.stdout)
            os.environ[name] = executable.strip()
    print("", file=sys.stdout)

# Pipeline
def create_pipeline(opts, directories, f_cmds):

    # .................................................................
    # Primordial
    # .................................................................
    # Commands file
    pipeline = ExecutablePipeline(name=__program__,  f_cmds=f_cmds, checkpoint_directory=directories["checkpoints"], log_directory=directories["log"])

    
    # ==========
    # Preprocessing
    # ==========
    
    program = "preprocessing"
    # Add to directories
    output_directory = directories["preprocessing"] 

    # Info
    step = 0
    description = "Symlink proteins"

    # i/o
    input_filepaths = [opts.proteins]
    output_filepaths = [
        os.path.join(directories["project"], "proteins.list"),
        os.path.join(directories["project"], "proteins.tsv"),
        os.path.join(directories["tmp"], "proteins.faa"),

    ]

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = preprocess(**params)

    pipeline.add_step(
                id=program,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
    )

  
    # ==========
    # HMMSearch
    # ==========
    step = 1

    program = "hmmsearch"
    program_label = "{}__{}".format(step, program)
    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))

    # Info
    description = "HMMSearch for proteins"


    # i/o
    input_filepaths = [
        os.path.join(directories["tmp"], "proteins.faa"),
        ]
    output_filenames = ["*.faa.gz", "markers.tsv"]
    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_hmmsearch_cmd(**params)

    pipeline.add_step(
                id=program,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
    )

    # ==========
    # MSA
    # ==========
    step = 2

    program = "msa"
    program_label = "{}__{}".format(step, program)
    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))

    # Info
    description = "Multiple sequence alignment"


    # i/o
    input_filepaths = [
        os.path.join(directories[("intermediate", "1__hmmsearch")], "markers.tsv"),
        ]
    output_filenames = ["concatenated_alignment.fasta",  "prefiltered_alignment_table.tsv.gz", "alignment_table.boolean.tsv.gz"]
    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_msa_cmd(**params)

    pipeline.add_step(
                id=program,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
    )

    # ==========
    # FastTree
    # ==========
    step = 3

    program = "fasttree"
    program_label = "{}__{}".format(step, program)
    # Add to directories
    output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))

    # Info
    description = "Tree construction via FastTree"


    # i/o
    input_filepaths = [
        os.path.join(directories[("intermediate", "2__msa")], "concatenated_alignment.fasta"),
        ]
    output_filenames = ["concatenated_alignment.fasttree.nw"]
    output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

    params = {
        "input_filepaths":input_filepaths,
        "output_filepaths":output_filepaths,
        "output_directory":output_directory,
        "opts":opts,
        "directories":directories,
    }

    cmd = get_fasttree_cmd(**params)

    pipeline.add_step(
                id=program,
                description = description,
                step=step,
                cmd=cmd,
                input_filepaths = input_filepaths,
                output_filepaths = output_filepaths,
                validate_inputs=True,
                validate_outputs=True,
    )

    # ==========
    # IQTree
    # ==========
    if not opts.no_iqtree:
        step += 1

        program = "iqtree"
        program_label = "{}__{}".format(step, program)
        # Add to directories
        output_directory = directories[("intermediate",  program_label)] = create_directory(os.path.join(directories["intermediate"], program_label))

        # Info
        description = "Tree construction via IQTree"


        # i/o
        input_filepaths = [
            os.path.join(directories[("intermediate", "2__msa")], "concatenated_alignment.fasta"),
            ]
        output_filenames = ["output.treefile"]
        output_filepaths = list(map(lambda filename: os.path.join(output_directory, filename), output_filenames))

        params = {
            "input_filepaths":input_filepaths,
            "output_filepaths":output_filepaths,
            "output_directory":output_directory,
            "opts":opts,
            "directories":directories,
        }

        cmd = get_iqtree_cmd(**params)

        pipeline.add_step(
                    id=program,
                    description = description,
                    step=step,
                    cmd=cmd,
                    input_filepaths = input_filepaths,
                    output_filepaths = output_filepaths,
                    validate_inputs=True,
                    validate_outputs=False,
        )

    # =============
    # Symlink
    # =============
    program = "symlink"
    # Add to directories
    output_directory = directories["output"]

    # Info
    step += 1
    description = "Symlinking relevant output files"

    # i/o
    input_filepaths = [
        os.path.join(directories[("intermediate", "2__msa")], "prefiltered_alignment_table.tsv.gz"),
        os.path.join(directories[("intermediate", "2__msa")], "alignment_table.boolean.tsv.gz"), 
        os.path.join(directories[("intermediate", "2__msa")], "concatenated_alignment.fasta"),
        os.path.join(directories[("intermediate", "3__fasttree")], "concatenated_alignment.fasttree.nw"),
    ]
    if not opts.no_iqtree:
        input_filepaths += [os.path.join(directories[("intermediate", "4__iqtree")], "output.treefile")]


    output_filenames =  map(lambda fp: fp.split("/")[-1], input_filepaths)
    output_filepaths = list(map(lambda fn:os.path.join(directories["output"], fn), output_filenames))

    params = {
    "input_filepaths":input_filepaths,
    "output_filepaths":output_filepaths,
    "output_directory":output_directory,
    "opts":opts,
    "directories":directories,
    }

    cmd = get_symlink_cmd(**params)
    pipeline.add_step(
            id=program,
            description = description,
            step=step,
            cmd=cmd,
            input_filepaths = input_filepaths,
            output_filepaths = output_filepaths,
            validate_inputs=True,
            validate_outputs=False,
    )

    return pipeline

# Configure parameters
def configure_parameters(opts, directories):
    if opts.hmmsearch_threshold.lower() == "e":
        opts.hmmsearch_threshold = None
    assert_acceptable_arguments(opts.hmm_marker_field, {"accession", "name"})
    # Set environment variables
    add_executables_to_environment(opts=opts)

def main(args=None):
    # Path info
    script_directory  =  os.path.dirname(os.path.abspath( __file__ ))
    script_filename = __program__
    # Path info
    description = """
    Running: {} v{} via Python v{} | {}""".format(__program__, __version__, sys.version.split(" ")[0], sys.executable)
    usage = "{} -d <database_hmms> -a <proteins> -o <output_directory>".format(__program__)
    epilog = "Copyright 2021 Josh L. Espinoza (jespinoz@jcvi.org)"

    # Parser
    parser = argparse.ArgumentParser(description=description, usage=usage, epilog=epilog, formatter_class=argparse.RawTextHelpFormatter)
    # Pipeline
    parser_io = parser.add_argument_group('Required I/O arguments')
    parser_io.add_argument("-d", "--database_hmm", type=str,  help=f"path/to/HMM database of markers")
    parser_io.add_argument("-a","--proteins", type=str, help = "Can be the following format: 1) Tab-seperated value table of [id_mag]<tab>[path/to/protein.fasta]; 2) List of filepaths [path/to/protein.fasta]; or 3) Directory of protein fasta using --protein_extension")
    parser_io.add_argument("-o","--output_directory", type=str, default="veba_output/phylogeny", help = "path/to/project_directory [Default: veba_output/phylogeny]")
    parser_io.add_argument("-x", "--extension", type=str, default="faa", help = "Fasta file extension for proteins if a list is provided [Default: faa]")

    # Utility
    parser_utility = parser.add_argument_group('Utility arguments')
    parser_utility.add_argument("--path_config", type=str,  default="CONDA_PREFIX", help="path/to/config.tsv [Default: CONDA_PREFIX]")  #site-packges in future
    parser_utility.add_argument("-p", "--n_jobs", type=int, default=1, help = "Number of threads [Default: 1]")
    parser_utility.add_argument("--random_state", type=int, default=0, help = "Random state [Default: 0]")
    parser_utility.add_argument("--restart_from_checkpoint", type=str, default=None, help = "Restart from a particular checkpoint [Default: None]")
    parser_utility.add_argument("-v", "--version", action='version', version="{} v{}".format(__program__, __version__))

    # HMMER
    parser_hmmer = parser.add_argument_group('HMMSearch arguments')
    parser_hmmer.add_argument("--hmmsearch_threshold", type=str, default="e", help="HMMSearch | Threshold {cut_ga, cut_nc, gut_tc, e} [Default:  e]")
    parser_hmmer.add_argument("--hmmsearch_evalue", type=float, default=10.0, help="Diamond | E-Value [Default: 10.0]")
    parser_hmmer.add_argument("--hmmsearch_options", type=str, default="", help="Diamond | More options (e.g. --arg 1 ) [Default: '']")
    parser_hmmer.add_argument("-f", "--hmm_marker_field", default="accession", type=str, help="HMM reference type (accession, name) [Default: accession")
    parser_hmmer.add_argument("-s","--scores_cutoff", type=str, help = "path/to/scores_cutoff.tsv. No header. [id_hmm]<tab>[score]")

    # Muscle
    parser_alignment = parser.add_argument_group('Alignment arguments')
    parser_alignment.add_argument("-g", "--minimum_genomes_aligned_ratio", type=float,  default=0.95, help = "Minimum ratio of genomes include in alignment. This removes markers that are under represented. [Default: 0.95]")
    parser_alignment.add_argument("-m", "--minimum_markers_aligned_ratio", type=float,  default=0.2, help = "Minimum ratio of markers aligned. This removes genomes with few markers. Note, this is based on detected markers and NOT total markers in original HMM. [Default: 0.2]")
    parser_alignment.add_argument("--muscle_options", type=str, default="", help="MUSCLE | More options (e.g. --arg 1 ) [Default: '']")
    parser_alignment.add_argument("--clipkit_mode", type=str, default="smart-gap", help="ClipKIT | Trimming mode [Default: smart-gap]")
    parser_alignment.add_argument("--clipkit_options", type=str, default="", help="ClipKIT | More options (e.g. --arg 1 ) [Default: '']")



    # Tree
    parser_tree = parser.add_argument_group('Tree arguments')
    parser_tree.add_argument("--fasttree_options", type=str, default="", help="FastTree | More options (e.g. --arg 1 ) [Default: '']")
    parser_tree.add_argument("--no_iqtree", action="store_true", help="IQTree | Don't run IQTree")
    parser_tree.add_argument("--iqtree_model", type=str, default="MFP", help="IQTree | Model finder [Default: MFP]")
    parser_tree.add_argument("--iqtree_mset", type=str, default="WAG,LG", help="IQTree | Model set to choose from [Default: WAG,LG]")
    parser_tree.add_argument("--iqtree_bootstraps", type=int, default=1000, help="IQTree | Bootstraps [Default: 1000]")
    parser_tree.add_argument("--iqtree_options", type=str, default="", help="IQTree | More options (e.g. --arg 1 ) [Default: '']")

    # Options
    opts = parser.parse_args()
    opts.script_directory  = script_directory
    opts.script_filename = script_filename

    # Directories
    directories = dict()
    directories["project"] = create_directory(opts.output_directory)
    directories["preprocessing"] = create_directory(os.path.join(directories["project"], "preprocessing"))
    directories["output"] = create_directory(os.path.join(directories["project"], "output"))
    directories["log"] = create_directory(os.path.join(directories["project"], "log"))
    directories["tmp"] = create_directory(os.path.join(directories["project"], "tmp"))
    directories["checkpoints"] = create_directory(os.path.join(directories["project"], "checkpoints"))
    directories["intermediate"] = create_directory(os.path.join(directories["project"], "intermediate"))
    os.environ["TMPDIR"] = directories["tmp"]

    # Info
    print(format_header(__program__, "="), file=sys.stdout)
    print(format_header("Configuration:", "-"), file=sys.stdout)
    print("Python version:", sys.version.replace("\n"," "), file=sys.stdout)
    print("Python path:", sys.executable, file=sys.stdout) #sys.path[2]
    print("Script version:", __version__, file=sys.stdout)
    print("Moment:", get_timestamp(), file=sys.stdout)
    print("Directory:", os.getcwd(), file=sys.stdout)
    print("Commands:", list(filter(bool,sys.argv)),  sep="\n", file=sys.stdout)
    configure_parameters(opts, directories)
    sys.stdout.flush()

    # Symlink genomes

    # Run pipeline
    with open(os.path.join(directories["project"], "commands.sh"), "w") as f_cmds:
        pipeline = create_pipeline(
                     opts=opts,
                     directories=directories,
                     f_cmds=f_cmds,
        )
        pipeline.compile()
        pipeline.execute(restart_from_checkpoint=opts.restart_from_checkpoint)

if __name__ == "__main__":
    main()
