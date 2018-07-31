import pytest
import json
from pprint import pprint

import numpy as np
from numba import cuda
import libgdf_cffi
from libgdf_cffi import ffi, libgdf

try:
    import pyarrow as pa
except ImportError as msg:
    print('Failed to import pyarrow: {}'.format(msg))
    pa = None

expected_values = """
0,orange,0.4713545411053003
1,orange,0.003790919207527499
2,orange,0.4396940888188392
3,apple,0.5693619092183622
4,pear,0.10894215574048405
5,pear,0.09547296520000881
6,orange,0.4123169425191555
7,apple,0.4125838710498503
8,orange,0.1904218750870219
9,apple,0.9289366739893021
10,orange,0.9330387015860205
11,pear,0.46564799732291595
12,apple,0.8573176464520044
13,pear,0.21566885180419648
14,orange,0.9199361970381871
15,orange,0.9819955872277085
16,apple,0.415964752238025
17,grape,0.36941794781567516
18,apple,0.9761832273396152
19,grape,0.16672327312068824
20,orange,0.13311815129622395
21,orange,0.6230693626648358
22,pear,0.7321171864853122
23,grape,0.23106658283660853
24,pear,0.0198404248930919
25,orange,0.4032931749027482
26,grape,0.665861129515741
27,pear,0.10253071509254097
28,orange,0.15243296681892238
29,pear,0.3514868485827787
"""


def get_expected_values():
    lines = filter(lambda x: x.strip(), expected_values.splitlines())
    rows = [ln.split(',') for ln in lines]
    return [(int(idx), name, float(weight))
            for idx, name, weight in rows]

def make_batch():
    indices, names, weights = zip(*get_expected_values())
    d_index = pa.array(indices).cast(pa.int32())
    d_name = pa.DictionaryArray.from_arrays(d_index, np.array(names, dtype=object))
    # TODO: in the original test data len(d_name)==4, here we have len(d_name)==30.
    d_weight = pa.array(weights)
    batch = pa.RecordBatch.from_arrays([d_index, d_name, d_weight], ['idx', 'name', 'weight'])
    return batch

def test_ipc_new():

    batch = make_batch()
    schema_bytes = batch.schema.serialize().to_pybytes()
    recordbatches_bytes = batch.serialize().to_pybytes()
    
    cpu_data = np.ndarray(shape=len(schema_bytes), dtype=np.byte,
                          buffer=bytearray(schema_bytes))

    # Use GDF IPC parser
    schema_ptr = ffi.cast("void*", cpu_data.ctypes.data)
    ipch = libgdf.gdf_ipc_parser_open(schema_ptr, cpu_data.size)

    if libgdf.gdf_ipc_parser_failed(ipch):
        print('FAILURE:',ffi.string(libgdf.gdf_ipc_parser_get_error(ipch)))
        assert 0
    jsonraw = libgdf.gdf_ipc_parser_get_schema_json(ipch)
    jsontext = ffi.string(jsonraw).decode()
    json_schema = json.loads(jsontext)
    print('json_schema:')
    pprint(json_schema)

    rb_cpu_data = np.ndarray(shape=len(recordbatches_bytes), dtype=np.byte,
                             buffer=bytearray(recordbatches_bytes))
    rb_gpu_data = cuda.to_device(rb_cpu_data)
    del cpu_data

    devptr = ffi.cast("void*", rb_gpu_data.device_ctypes_pointer.value)

    libgdf.gdf_ipc_parser_open_recordbatches(ipch, devptr, rb_gpu_data.size)

    if libgdf.gdf_ipc_parser_failed(ipch):
        print('FAILURE:',ffi.string(libgdf.gdf_ipc_parser_get_error(ipch)))
        assert 0

    jsonraw = libgdf.gdf_ipc_parser_get_layout_json(ipch)
    jsontext = ffi.string(jsonraw).decode()
    json_rb = json.loads(jsontext)
    print('json_rb:')
    pprint(json_rb)

    offset = libgdf.gdf_ipc_parser_get_data_offset(ipch)

    libgdf.gdf_ipc_parser_close(ipch)

    # Check
    dicts = json_schema['dictionaries']
    assert len(dicts) == 1
    dictdata = dicts[0]['data']['columns'][0]['DATA']
    assert set(dictdata) == {'orange', 'apple', 'pear', 'grape'}

    gpu_data = rb_gpu_data[offset:]

    schema_fields = json_schema['schema']['fields']
    assert len(schema_fields) == 3
    field_names = [f['name'] for f in schema_fields]
    assert field_names == ['idx', 'name', 'weight']

    # check the dictionary id in schema
    assert schema_fields[1]['dictionary']['id'] == dicts[0]['id']

    # Get "idx" column
    idx_buf_off = json_rb[0]['data_buffer']['offset']
    idx_buf_len = json_rb[0]['data_buffer']['length']
    idx_buf = gpu_data[idx_buf_off:][:idx_buf_len]
    assert json_rb[0]['dtype']['name'] == 'INT32'
    idx_size = json_rb[0]['length']
    assert idx_size == 30
    idx_data = np.ndarray(shape=idx_size, dtype=np.int32,
                          buffer=idx_buf.copy_to_host())
    print('idx_data:')
    print(idx_data)

    # Get "name" column
    name_buf_off = json_rb[1]['data_buffer']['offset']
    name_buf_len = json_rb[1]['data_buffer']['length']
    name_buf = gpu_data[name_buf_off:][:name_buf_len]
    assert json_rb[1]['dtype']['name'] == 'DICTIONARY'
    name_size = json_rb[1]['length']
    name_data = np.ndarray(shape=name_size, dtype=np.int32,
                           buffer=name_buf.copy_to_host())
    print('name_data:')
    print(name_data)

    # Get "weight" column
    weight_buf_off = json_rb[2]['data_buffer']['offset']
    weight_buf_len = json_rb[2]['data_buffer']['length']
    weight_buf = gpu_data[weight_buf_off:][:weight_buf_len]
    assert json_rb[2]['dtype']['name'] == 'DOUBLE'
    weight_size = json_rb[2]['length']
    weight_data = np.ndarray(shape=weight_size, dtype=np.float64,
                             buffer=weight_buf.copy_to_host())
    print('weight_data:')
    print(weight_data)

    # verify data
    sortedidx = np.argsort(idx_data)
    idx_data = idx_data[sortedidx]
    name_data = name_data[sortedidx]
    weight_data = weight_data[sortedidx]

    got_iter = zip(idx_data, name_data, weight_data)
    for expected, got in zip(get_expected_values(), got_iter):
        assert expected[0] == got[0]
        assert expected[1] == dictdata[got[1]]
        assert expected[2] == got[2]
    
def test_ipc():
    # The following byte sequences assume arrow metadata version 3
    schema_bytes = b'\xa8\x01\x00\x00\x10\x00\x00\x00\x0c\x00\x0e\x00\x06\x00\x05\x00\x08\x00\x00\x00\x0c\x00\x00\x00\x00\x01\x02\x00\x10\x00\x00\x00\x00\x00\n\x00\x08\x00\x00\x00\x04\x00\x00\x00\n\x00\x00\x00\x04\x00\x00\x00\x03\x00\x00\x00\x18\x01\x00\x00p\x00\x00\x00\x04\x00\x00\x00\x08\xff\xff\xff\x00\x00\x01\x03@\x00\x00\x00$\x00\x00\x00\x14\x00\x00\x00\x04\x00\x00\x00\x02\x00\x00\x00$\x00\x00\x00\x18\x00\x00\x00\x00\x00\x00\x00\x00\x00\x06\x00\x08\x00\x06\x00\x06\x00\x00\x00\x00\x00\x02\x00\xe8\xfe\xff\xff@\x00\x01\x00\xf0\xfe\xff\xff\x01\x00\x02\x00\x06\x00\x00\x00weight\x00\x00\x14\x00\x1e\x00\x08\x00\x06\x00\x07\x00\x0c\x00\x10\x00\x14\x00\x18\x00\x00\x00\x14\x00\x00\x00\x00\x00\x01\x05|\x00\x00\x00T\x00\x00\x00\x18\x00\x00\x00D\x00\x00\x000\x00\x00\x00\x00\x00\n\x00\x14\x00\x08\x00\x04\x00\x00\x00\n\x00\x00\x00\x10\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00p\xff\xff\xff\x00\x00\x00\x01 \x00\x00\x00\x03\x00\x00\x000\x00\x00\x00$\x00\x00\x00\x10\x00\x00\x00\x00\x00\x00\x00\x04\x00\x04\x00\x04\x00\x00\x00|\xff\xff\xff\x08\x00\x01\x00\x08\x00\x08\x00\x06\x00\x00\x00\x08\x00\x00\x00\x00\x00 \x00\x94\xff\xff\xff\x01\x00\x02\x00\x04\x00\x00\x00name\x00\x00\x00\x00\x14\x00\x18\x00\x08\x00\x06\x00\x07\x00\x0c\x00\x00\x00\x10\x00\x14\x00\x00\x00\x14\x00\x00\x00\x00\x00\x01\x02L\x00\x00\x00$\x00\x00\x00\x14\x00\x00\x00\x04\x00\x00\x00\x02\x00\x00\x000\x00\x00\x00\x1c\x00\x00\x00\x00\x00\x00\x00\x08\x00\x0c\x00\x08\x00\x07\x00\x08\x00\x00\x00\x00\x00\x00\x01 \x00\x00\x00\xf8\xff\xff\xff \x00\x01\x00\x08\x00\x08\x00\x04\x00\x06\x00\x08\x00\x00\x00\x01\x00\x02\x00\x03\x00\x00\x00idx\x00\xc8\x00\x00\x00\x14\x00\x00\x00\x00\x00\x00\x00\x0c\x00\x14\x00\x06\x00\x05\x00\x08\x00\x0c\x00\x0c\x00\x00\x00\x00\x02\x02\x00\x14\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x08\x00\x12\x00\x08\x00\x04\x00\x08\x00\x00\x00\x18\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\n\x00\x18\x00\x0c\x00\x04\x00\x08\x00\n\x00\x00\x00d\x00\x00\x00\x10\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x06\x00\x00\x00\x0b\x00\x00\x00\x0f\x00\x00\x00\x14\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00orangeapplepeargrape\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    cpu_data = np.ndarray(shape=len(schema_bytes), dtype=np.byte,
                          buffer=bytearray(schema_bytes))

    # Use GDF IPC parser
    schema_ptr = ffi.cast("void*", cpu_data.ctypes.data)
    ipch = libgdf.gdf_ipc_parser_open(schema_ptr, cpu_data.size)

    if libgdf.gdf_ipc_parser_failed(ipch):
        print('FAILURE:', libgdf.gdf_ipc_parser_get_error(ipch))
        assert 0
    jsonraw = libgdf.gdf_ipc_parser_get_schema_json(ipch)
    jsontext = ffi.string(jsonraw).decode()
    json_schema = json.loads(jsontext)
    print('json_schema:')
    pprint(json_schema)

    recordbatches_bytes = b'\x1c\x01\x00\x00\x14\x00\x00\x00\x00\x00\x00\x00\x0c\x00\x16\x00\x06\x00\x05\x00\x08\x00\x0c\x00\x0c\x00\x00\x00\x00\x03\x02\x00\x18\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\n\x00\x18\x00\x0c\x00\x04\x00\x08\x00\n\x00\x00\x00\xac\x00\x00\x00\x10\x00\x00\x00\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x06\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x10\x00\x00\x00\x11\x00\x00\x00\x12\x00\x00\x00\x13\x00\x00\x00\x04\x00\x00\x00\x05\x00\x00\x00\x06\x00\x00\x00\x07\x00\x00\x00\x14\x00\x00\x00\x15\x00\x00\x00\x16\x00\x00\x00\x17\x00\x00\x00\x08\x00\x00\x00\t\x00\x00\x00\n\x00\x00\x00\x0b\x00\x00\x00\x18\x00\x00\x00\x19\x00\x00\x00\x1a\x00\x00\x00\x1b\x00\x00\x00\x0c\x00\x00\x00\r\x00\x00\x00\x0e\x00\x00\x00\x0f\x00\x00\x00\x1c\x00\x00\x00\x1d\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x01\x00\x00\x00\x03\x00\x00\x00\x01\x00\x00\x00\x03\x00\x00\x00\x02\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x02\x00\x00\x00\x01\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x16\x93\xb7<\xac*\xde?\x00Y\x94@"\x0eo?\xf8+\xee\xac\xf2#\xdc?\xa4\xcauw68\xe2?\xf8\xaa\xc9\x9f*\x9f\xda?\xe0\x1e\x1b-\x8b\xa4\xd7?\xe6y\x8a\x9b\xe4<\xef?\x08\x89\xc4.0W\xc5?h\xa5\x0f\x14\xa2\xe3\xbb?\xc0\xa9/\x8f\xeap\xb8?\x0c7\xed\x99fc\xda?:\tA.\xc6g\xda?\x1c\x1f)\xfd\x03\n\xc1?\xfe\x1e\xf9(/\xf0\xe3?\x08h\x99\x05\x81m\xe7?\xa0\xa8=\xfc\x96\x93\xcd?x\x8b\xf8v\xbe_\xc8?\xa2\xd9Zg\xd9\xb9\xed?;\xdb\xa6\xfas\xdb\xed?\xd8\xc9\xfcA-\xcd\xdd?@\xe27`\x0cQ\x94?d\x11:-\x8e\xcf\xd9?\xc9S\xde\xff\xbbN\xe5?\xe0o(\xf4s?\xba?\x0bq\xb9j%o\xeb?\x10\xe8\xa1t\t\x9b\xcb?\xa5\xf0\x15\t\x1ep\xed?\xc7\xb2~\x02\x82l\xef?0\xe6\xa8g\xec\x82\xc3?\xe0\xc6\xe8\xb1\xc2~\xd6?\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

    rb_cpu_data = np.ndarray(shape=len(recordbatches_bytes), dtype=np.byte,
                             buffer=bytearray(recordbatches_bytes))
    rb_gpu_data = cuda.to_device(rb_cpu_data)
    del cpu_data

    devptr = ffi.cast("void*", rb_gpu_data.device_ctypes_pointer.value)

    libgdf.gdf_ipc_parser_open_recordbatches(ipch, devptr, rb_gpu_data.size)

    if libgdf.gdf_ipc_parser_failed(ipch):
        print(libgdf.gdf_ipc_parser_get_error(ipch))
        assert 0

    jsonraw = libgdf.gdf_ipc_parser_get_layout_json(ipch)
    jsontext = ffi.string(jsonraw).decode()
    json_rb = json.loads(jsontext)
    print('json_rb:')
    pprint(json_rb)

    offset = libgdf.gdf_ipc_parser_get_data_offset(ipch)

    libgdf.gdf_ipc_parser_close(ipch)

    # Check
    dicts = json_schema['dictionaries']
    assert len(dicts) == 1
    dictdata = dicts[0]['data']['columns'][0]['DATA']
    assert set(dictdata) == {'orange', 'apple', 'pear', 'grape'}

    gpu_data = rb_gpu_data[offset:]

    schema_fields = json_schema['schema']['fields']
    assert len(schema_fields) == 3
    field_names = [f['name'] for f in schema_fields]
    assert field_names == ['idx', 'name', 'weight']

    # check the dictionary id in schema
    assert schema_fields[1]['dictionary']['id'] == dicts[0]['id']

    # Get "idx" column
    idx_buf_off = json_rb[0]['data_buffer']['offset']
    idx_buf_len = json_rb[0]['data_buffer']['length']
    idx_buf = gpu_data[idx_buf_off:][:idx_buf_len]
    assert json_rb[0]['dtype']['name'] == 'INT32'
    idx_size = json_rb[0]['length']
    assert idx_size == 30
    idx_data = np.ndarray(shape=idx_size, dtype=np.int32,
                          buffer=idx_buf.copy_to_host())
    print('idx_data:')
    print(idx_data)

    # Get "name" column
    name_buf_off = json_rb[1]['data_buffer']['offset']
    name_buf_len = json_rb[1]['data_buffer']['length']
    name_buf = gpu_data[name_buf_off:][:name_buf_len]
    assert json_rb[1]['dtype']['name'] == 'DICTIONARY'
    name_size = json_rb[1]['length']
    name_data = np.ndarray(shape=name_size, dtype=np.int32,
                           buffer=name_buf.copy_to_host())
    print('name_data:')
    print(name_data)

    # Get "weight" column
    weight_buf_off = json_rb[2]['data_buffer']['offset']
    weight_buf_len = json_rb[2]['data_buffer']['length']
    weight_buf = gpu_data[weight_buf_off:][:weight_buf_len]
    assert json_rb[2]['dtype']['name'] == 'DOUBLE'
    weight_size = json_rb[2]['length']
    weight_data = np.ndarray(shape=weight_size, dtype=np.float64,
                             buffer=weight_buf.copy_to_host())
    print('weight_data:')
    print(weight_data)

    # verify data
    sortedidx = np.argsort(idx_data)
    idx_data = idx_data[sortedidx]
    name_data = name_data[sortedidx]
    weight_data = weight_data[sortedidx]

    got_iter = zip(idx_data, name_data, weight_data)
    for expected, got in zip(get_expected_values(), got_iter):
        assert expected[0] == got[0]
        assert expected[1] == dictdata[got[1]]
        assert expected[2] == got[2]

if pa is None:
    test_ipc_new = pytest.mark.skip(message = 'need compatible pyarrow to generate test data')(test_ipc_new)
    test_ipc = pytest.mark.skip(message = 'requires arrow 0.7.1')(test_ipc)
elif pa.__version__ != '0.7.1':
    test_ipc = pytest.mark.skip(message = 'requires arrow 0.7.1, got {}'.format(pa.__version__))(test_ipc)    
