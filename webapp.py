#!/usr/bin/env python3

import pathlib
import time
import sys
import shutil
import logging
import tempfile
import utils
import dariah_topics
import flask
import pandas as pd
import numpy as np
import bokeh.plotting
import bokeh.embed
import werkzeug.utils


TEMPDIR = tempfile.mkdtemp()  # Storing logfile, dumping temporary data, etc.
NUM_KEYS = 8  # The number of topic keys for the topics table


if getattr(sys, 'frozen', False):
    # If the script is frozen by PyInstaller
    root = pathlib.Path(sys._MEIPASS)
    app = flask.Flask(import_name=__name__,
                      template_folder=str(pathlib.Path(root, 'templates')),
                      static_folder=str(pathlib.Path(root, 'static')))
    bokeh_resources = str(pathlib.Path(root, 'static', 'bokeh_templates'))
else:
    app = flask.Flask(import_name=__name__)
    bokeh_resources = str(pathlib.Path('static', 'bokeh_templates'))


@app.route('/')
def index():
    """
    Renders the main page.
    """
    return flask.render_template('index.html')


@app.route('/help')
def help():
    """
    Renders the help page.
    """
    return flask.render_template('help.html')


@app.route('/modeling', methods=['POST'])
def modeling():
    """
    Streams the modeling page, printing useful information to screen.
    The generated data will be dumped into the tempdir (specified above).
    """
    data = ["running", "running", "error"]
    data1 = ["ok", "cool", "nice"]

    @flask.stream_with_context
    def generate():
        for x, item in zip(data1, data):
            yield item, x, "B", "C", "D", "E"
            time.sleep(3)

    progress = generate()

    def stream_template(template_name, **context):
        app.update_template_context(context)
        t = app.jinja_env.get_template(template_name)
        return t.stream(context)
    return flask.Response(stream_template('modeling.html', info=progress))


@app.route('/model')
def model():
    """
    Reads the dumped data and renders the output page.
    """
    data_path = str(pathlib.Path(TEMPDIR, 'data.pickle'))
    parameter_path = str(pathlib.Path(TEMPDIR, 'parameter.csv'))
    topics_path = str(pathlib.Path(TEMPDIR, 'topics.csv'))

    data = utils.decompress(data_path)
    parameter = pd.read_csv(parameter_path, index_col=0, encoding='utf-8')
    parameter.columns = ['']  # remove column names
    topics = pd.read_csv(topics_path, index_col=0, encoding='utf-8')

    data['parameter'] = [parameter.to_html(classes='parameter', border=0)]
    data['topics'] = [topics.to_html(classes='topics')]
    return flask.render_template('model.html', **data)


@app.after_request
def add_header(r):
    """
    Handles the cache.
    """
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    r.headers['Pragma'] = 'no-cache'
    r.headers['Expires'] = '0'
    r.headers['Cache-Control'] = 'public, max-age=0'
    return r


def create_model():
    start = time.time()

    try:
        user_input = {'files': flask.request.files.getlist('files'),
                      'num_topics': int(flask.request.form['num_topics']),
                      'num_iterations': int(flask.request.form['num_iterations'])}

        if flask.request.files.get('stopword_list', None):
            user_input['stopwords'] = flask.request.files['stopword_list']
        else:
            user_input['mfw'] = int(flask.request.form['mfw_threshold'])

        parameter = pd.Series()
        parameter['Corpus size, in documents'] = len(user_input['files'])
        parameter['Corpus size (raw), in tokens'] = 0

        tokenized_corpus = pd.Series()
        for file in user_input['files']:
            filename = pathlib.Path(werkzeug.utils.secure_filename(file.filename))
            if filename.suffix == '.txt':
                text = file.read().decode('utf-8')
            else:
                text = utils.process_xml(file)
            tokens = list(dariah_topics.preprocessing.tokenize(text))
            tokenized_corpus[filename.stem] = tokens
            parameter['Corpus size (raw), in tokens'] += len(tokens)
            file.flush()

        document_labels = tokenized_corpus.index
        document_term_matrix = dariah_topics.preprocessing.create_document_term_matrix(tokenized_corpus, document_labels)

        group = ['Document size (raw)' for i in range(parameter['Corpus size, in documents'])]
        corpus_stats = pd.DataFrame({'score': np.array(document_term_matrix.sum(axis=1)),
                                     'group': group})

        try:
            stopwords = dariah_topics.preprocessing.find_stopwords(document_term_matrix, user_input['mfw'])
        except KeyError:
            stopwords = user_input['stopwords'].read().decode('utf-8')
            stopwords = set(dariah_topics.preprocessing.tokenize(stopwords))
        hapax_legomena = dariah_topics.preprocessing.find_hapax_legomena(document_term_matrix)
        features = stopwords.union(hapax_legomena)
        features = [token for token in features if token in document_term_matrix.columns]
        document_term_matrix = document_term_matrix.drop(features, axis=1)

        group = ['Document size (clean)' for n in range(parameter['Corpus size, in documents'])]
        corpus_stats = corpus_stats.append(pd.DataFrame({'score': np.array(document_term_matrix.sum(axis=1)),
                                                         'group': group}))

        parameter['Corpus size (clean), in tokens'] = int(document_term_matrix.values.sum())

        document_term_arr = document_term_matrix.as_matrix().astype(int)
        vocabulary = document_term_matrix.columns

        parameter['Size of vocabulary, in tokens'] = len(vocabulary)
        parameter['Number of topics'] = user_input['num_topics']
        parameter['Number of iterations'] = user_input['num_iterations']

        model = enthread(target=lda_modeling,
                         args=(document_term_arr,
                               user_input['num_topics'],
                               user_input['num_iterations'],
                               TEMPDIR))
        while True:
            msg = utils.read_logfile(str(pathlib.Path(TEMPDIR, 'topicmodeling.log')))

            if msg == None:
                model = model.get()
                break
            else:
                yield msg

        parameter['The model log-likelihood'] = round(model.loglikelihood())

        topics = dariah_topics.postprocessing.show_topics(model=model,
                                                          vocabulary=vocabulary,
                                                          num_keys=NUM_KEYS)
        topics.columns = ['Key {0}'.format(i) for i in range(1, NUM_KEYS + 1)]
        topics.index = ['Topic {0}'.format(i) for i in range(1, user_input['num_topics'] + 1)]

        document_topics = dariah_topics.postprocessing.show_document_topics(model=model,
                                                                            topics=topics,
                                                                            document_labels=document_labels)
        if document_topics.shape[0] < document_topics.shape[1]:
            if document_topics.shape[1] < 20:
                height = 20 * 28
            else:
                height = document_topics.shape[1] * 28
            document_topics_heatmap = document_topics.T
        else:
            if document_topics.shape[0] < 20:
                height = 20 * 28
            else:
                height = document_topics.shape[0] * 28
            document_topics_heatmap = document_topics

        fig = dariah_topics.visualization.PlotDocumentTopics(document_topics_heatmap,
                                                             enable_notebook=False)
        heatmap = fig.interactive_heatmap(height=height,
                                          sizing_mode='scale_width',
                                          tools='hover, pan, reset, wheel_zoom, zoom_in, zoom_out')

        bokeh.plotting.output_file(str(pathlib.Path(tempdir, 'heatmap.html')))
        bokeh.plotting.save(heatmap)

        heatmap_script, heatmap_div = bokeh.embed.components(heatmap)

        corpus_boxplot = utils.boxplot(corpus_stats)
        corpus_boxplot_script, corpus_boxplot_div = bokeh.embed.components(corpus_boxplot)
        bokeh.plotting.output_file(str(pathlib.Path(TEMPDIR, 'corpus_statistics.html')))
        bokeh.plotting.save(corpus_boxplot)

        if document_topics.shape[1] < 10:
            height = 10 * 18
        else:
            height = document_topics.shape[1] * 18
        topics_barchart = utils.barchart(document_topics, height=height, topics=topics)
        topics_script, topics_div = bokeh.embed.components(topics_barchart)
        bokeh.plotting.output_file(str(pathlib.Path(TEMPDIR, 'topics_barchart.html')))
        bokeh.plotting.save(topics_barchart)

        if document_topics.shape[0] < 10:
            height = 10 * 18
        else:
            height = document_topics.shape[0] * 18
        documents_barchart = utils.barchart(document_topics.T, height=height)
        documents_script, documents_div = bokeh.embed.components(documents_barchart)
        bokeh.plotting.output_file(str(pathlib.Path(TEMPDIR, 'document_topics_barchart.html')))
        bokeh.plotting.save(documents_barchart)


        with open(str(pathlib.Path(bokeh_resources, 'render_js.txt')), 'r', encoding='utf-8') as file:
            js_resources = file.read()
        with open(str(pathlib.Path(bokeh_resources, 'render_css.txt')), 'r', encoding='utf-8') as file:
            css_resources = file.read()

        end = time.time()
        passed_time = round((end - start) / 60)

        if passed_time == 0:
            parameter['Passed time, in seconds'] = round(end - start)
        else:
            parameter['Passed time, in minutes'] = passed_time

        parameter = pd.DataFrame(pd.Series(parameter))
        topics.to_csv(str(pathlib.Path(TEMPDIR, 'topics.csv')), encoding='utf-8')
        document_topics.to_csv(str(pathlib.Path(TEMPDIR, 'document_topics.csv')), encoding='utf-8')
        parameter.to_csv(str(pathlib.Path(TEMPDIR, 'parameter.csv')), encoding='utf-8')

        cwd = str(pathlib.Path(*pathlib.Path.cwd().parts[:-1]))
        shutil.make_archive(str(pathlib.Path(cwd, 'topicmodeling')), 'zip', TEMPDIR)

        data = {'heatmap_script': heatmap_script,
                'heatmap_div': heatmap_div,
                'topics_script': topics_script,
                'topics_div': topics_div,
                'documents_script': documents_script,
                'documents_div': documents_div,
                'js_resources': js_resources,
                'css_resources': css_resources,
                'corpus_boxplot_script': corpus_boxplot_script,
                'corpus_boxplot_div': corpus_boxplot_div,
                'cwd': cwd}
        utils.compress(data, str(pathlib.Path(TEMPDIR, 'data.pickle')))
        yield 'render_result', '', '', '', ''
    except Exception as error:
        print(error)
        yield 'error', str(error), '', '', ''



if __name__ == '__main__':
    app.debug = True
    app.run()
